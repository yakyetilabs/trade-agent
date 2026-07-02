"""Tool 1: classify_import_restriction (hybrid classifier).

Runs first. Classifies the analyst's *intent* for routing and — only when the
inquiry describes goods whose HTS code is missing/vague/disputed — additionally
proposes an HTS heading and restriction band with a calibrated confidence. The
*authoritative* restriction for an already-declared code comes from the
deterministic catalog join in ``lookup_shipment_manifest``; these proposal
fields are advisory.

A structured Vertex call constrains the model to the four routing intents; a
parse/transport failure degrades gracefully to ``unknown`` / confidence 0 rather
than throwing, so the agent loop can continue.
"""

from typing import Literal, cast

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import tool
from langchain_google_vertexai.model_garden import ChatAnthropicVertex
from pydantic import BaseModel, Field

from src.config import ANTHROPIC_VERTEX_REGION, GCP_PROJECT, VERTEX_PRIMARY_MODEL
from src.models import ImportClassification, InquiryIntent, RestrictionLevel
from src.tracing.trace_context import record_tool_call

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
classify, leave those two fields null — the authoritative restriction comes from the manifest
lookup, not from you."""


class _ClassifierOutput(BaseModel):
    """Structured-output schema for the LLM — constrained to the four routing intents."""

    intent: Literal[
        "tariff_lookup", "manifest_flag_resolution", "clearance_requirements", "unknown"
    ]
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    proposed_hts_heading: str | None = None
    restriction_band: (
        Literal["unrestricted", "license_required", "quota_controlled", "prohibited"] | None
    ) = None


def _classify_once(inquiry: str, model_id: str | None) -> _ClassifierOutput:
    """Single structured Vertex call — the test seam for this tool."""
    # No extended thinking here, deliberately: with_structured_output binds the schema
    # via forced tool_choice ({"type": "tool"}), which the API rejects when thinking is
    # enabled - and a router wants cheap, deterministic (temperature 0) output anyway.
    chat = ChatAnthropicVertex(
        project=GCP_PROJECT,
        location=ANTHROPIC_VERTEX_REGION,
        model_name=model_id or VERTEX_PRIMARY_MODEL,
        temperature=0.0,
        max_output_tokens=1024,
    )
    structured: Runnable[LanguageModelInput, _ClassifierOutput] = cast(
        "Runnable[LanguageModelInput, _ClassifierOutput]",
        chat.with_structured_output(_ClassifierOutput),
    )
    return structured.invoke([SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=inquiry)])


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
    """Pure core: classify an inquiry and append the call to the trace."""
    with record_tool_call("classify_import_restriction", {"inquiry": inquiry}) as out:
        try:
            classification = _to_classification(_classify_once(inquiry, model_id))
        except Exception as exc:  # noqa: BLE001 - any failure degrades to unknown
            classification = ImportClassification(
                intent=InquiryIntent.UNKNOWN,
                confidence=0.0,
                reasoning=f"Classifier error: {exc}",
            )
        out.update(classification.model_dump(mode="json"))
    return classification


@tool
def classify_import_restriction(inquiry: str) -> dict[str, object]:
    """Classify the analyst's inquiry intent and, when goods need classifying, propose an HTS
    heading and restriction band. Always call this first. Returns intent, confidence (0-1),
    reasoning, and optional proposed_hts_heading / restriction_band."""
    return run_classify_import_restriction(inquiry).model_dump(mode="json")
