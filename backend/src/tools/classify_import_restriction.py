"""Tool 1: classify_import_restriction (hybrid classifier).

Runs first. Classifies the analyst's *intent* for routing and - only when the
inquiry describes goods whose HTS code is missing/vague/disputed - additionally
proposes an HTS heading and restriction band with a calibrated confidence. The
*authoritative* restriction for an already-declared code comes from the
deterministic catalog join in ``lookup_shipment_manifest``; these proposal
fields are advisory.

A structured call constrains the model to the four routing intents; a
parse/transport failure degrades gracefully to ``unknown`` / confidence 0 rather
than throwing, so the agent loop can continue. The degraded reasoning always
starts with :data:`CLASSIFIER_ERROR_PREFIX` - the machine-readable contract the
eval provenance check keys on, so a degraded classification can never silently
pass as a model opinion.

The model binding comes from the runtime context (``model_id``), like the vendor
scope: the serving path binds the primary model, the eval runner binds the arm
under comparison, and neither is ever a model-facing argument. The call's token
usage is recorded on the trace so the run's billable split includes it.
"""

from typing import Literal, NamedTuple, cast

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from pydantic import BaseModel, Field

from src.config import VERTEX_PRIMARY_MODEL
from src.model_provider import build_chat_model
from src.models import ImportClassification, InquiryIntent, RestrictionLevel
from src.tools.vendor_context import VendorContext
from src.tracing.trace_context import record_tool_call

# The degraded-classification marker. Written exactly once (the except path below) and
# matched by the eval runner's classifier-health check; keep writer and readers on this
# single constant so the contract cannot drift.
CLASSIFIER_ERROR_PREFIX: str = "Classifier error:"

_SYSTEM_PROMPT = """You are an inquiry classifier for a US trade-compliance assistant.

Classify the analyst's inquiry into exactly one intent:
- "tariff_lookup": HTS classification, duty/tariff rates, or whether goods are restricted.
- "manifest_flag_resolution": why a specific shipment is held/flagged and how to resolve it.
- "clearance_requirements": documents, licenses, permits, or steps needed to clear an import.
- "unknown": anything else, or genuinely ambiguous inquiries.

Return a calibrated confidence (0-1); reserve >= 0.85 for unambiguous cases, with one or two
sentences of reasoning.

Only if the inquiry describes specific goods whose HTS code is missing, vague, or disputed,
additionally propose the most likely HTS heading (proposed_hts_heading) and its restriction band
(restriction_band). If the inquiry already cites an HTS code, or does not describe goods to
classify, leave those two fields null - the authoritative restriction comes from the manifest
lookup, not from you."""


class _ClassifierOutput(BaseModel):
    """Structured-output schema for the LLM - constrained to the four routing intents."""

    intent: Literal[
        "tariff_lookup", "manifest_flag_resolution", "clearance_requirements", "unknown"
    ]
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    proposed_hts_heading: str | None = None
    restriction_band: (
        Literal["unrestricted", "license_required", "quota_controlled", "prohibited"] | None
    ) = None


class _ClassifierCall(NamedTuple):
    """One structured classifier call: the parsed output plus its billable token usage.

    ``usage`` is the call's top-level ``usage_metadata`` int split (``None`` when the
    provider returned none) - recorded on the trace so the run's token accounting
    covers this internal model call, not just the agent loop's messages.
    """

    output: _ClassifierOutput
    usage: dict[str, int] | None


def _classify_once(inquiry: str, model_id: str | None) -> _ClassifierCall:
    """Single structured model call - the test seam for this tool.

    Built from the shared provider seam; ``with_structured_output`` constrains the model
    to the four routing intents. A router wants cheap, deterministic output, which the
    seam's ``temperature=0`` gives. ``include_raw=True`` keeps the raw ``AIMessage``
    alongside the parse so the call's ``usage_metadata`` survives; a parse failure
    raises and degrades via the caller's ``unknown`` path.
    """
    chat = build_chat_model(model_id or VERTEX_PRIMARY_MODEL)
    structured: Runnable[LanguageModelInput, dict[str, object]] = cast(
        "Runnable[LanguageModelInput, dict[str, object]]",
        chat.with_structured_output(_ClassifierOutput, include_raw=True),
    )
    result = structured.invoke(
        [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=inquiry)]
    )
    parsed = result.get("parsed")
    if not isinstance(parsed, _ClassifierOutput):
        raise ValueError(f"structured output did not parse: {result.get('parsing_error')}")
    raw = result.get("raw")
    usage: dict[str, int] | None = None
    if isinstance(raw, AIMessage) and raw.usage_metadata:
        # Only the top-level int split: the trace payload stays JSON-scalar (the
        # ToolCallLog contract), and these are the fields the run's token sum folds in.
        usage = {
            "input_tokens": raw.usage_metadata.get("input_tokens", 0),
            "output_tokens": raw.usage_metadata.get("output_tokens", 0),
            "total_tokens": raw.usage_metadata.get("total_tokens", 0),
        }
    return _ClassifierCall(output=parsed, usage=usage)


def _to_classification(parsed: _ClassifierOutput) -> ImportClassification:
    band = RestrictionLevel(parsed.restriction_band) if parsed.restriction_band else None
    return ImportClassification(
        intent=InquiryIntent(parsed.intent),
        confidence=parsed.confidence,
        reasoning=parsed.reasoning,
        proposed_hts_heading=parsed.proposed_hts_heading,
        restriction_band=band,
    )


def run_classify_import_restriction(
    inquiry: str, model_id: str | None = None
) -> ImportClassification:
    """Pure core: classify an inquiry and append the call (with usage) to the trace."""
    with record_tool_call("classify_import_restriction", {"inquiry": inquiry}) as out:
        try:
            call = _classify_once(inquiry, model_id)
            classification = _to_classification(call.output)
            if call.usage is not None:
                # Nested under its own key so the classification payload stays validatable
                # as-is; build_run_trace folds this into the run's billable token split.
                out["usage"] = call.usage
        except Exception as exc:  # noqa: BLE001 - any failure degrades to unknown
            classification = ImportClassification(
                intent=InquiryIntent.UNKNOWN,
                confidence=0.0,
                reasoning=f"{CLASSIFIER_ERROR_PREFIX} {exc}",
            )
        out.update(classification.model_dump(mode="json"))
    return classification


@tool
def classify_import_restriction(
    inquiry: str, runtime: ToolRuntime[VendorContext]
) -> dict[str, object]:
    """Classify the analyst's inquiry intent and, when goods need classifying, propose an HTS
    heading and restriction band. Always call this first. Returns intent, confidence (0-1),
    reasoning, and optional proposed_hts_heading / restriction_band."""
    return run_classify_import_restriction(inquiry, runtime.context["model_id"]).model_dump(
        mode="json"
    )
