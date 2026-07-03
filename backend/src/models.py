"""Pydantic v2 domain models for the trade-agent data domains.

Three domains back the persistence layer:

- ``Vendor``   -> Firestore ``trade-agent-Vendors``   (document id = ``vendor_id``)
- ``Shipment`` -> Firestore ``trade-agent-Shipments`` (document id = ``shipment_id``)
- ``HtsClause`` -> Pinecone ``trade-agent-hts-kb``     (vector id = ``hts_code``)

All three are populated exclusively from the synthetic generators in
``src/data/generators.py`` — there is no real trade data anywhere in this repo.

The models are ``frozen`` because these records are immutable reference/seed data:
generated once, written to a store, and read back. Firestore and the Pinecone
metadata payload both consume ``model_dump(mode="json")``, which renders the
``StrEnum`` members as their plain string values.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

# Document/vector id patterns. These are the *same* shapes the deterministic
# cross-vendor guard (Phase 3, src/safeguards/cross_vendor_guard.py) matches on:
# vendors as ``V-\d{3,}`` and shipments as ``S-\d{4,}``. Keeping the generators'
# ids inside these patterns is asserted by the data tests.
VENDOR_ID_PATTERN: str = r"^V-\d{3,}$"
SHIPMENT_ID_PATTERN: str = r"^S-\d{4,}$"


class GoodsCategory(StrEnum):
    """Broad import categories a vendor is scoped to and an HTS clause covers."""

    ELECTRONICS = "electronics"
    TEXTILES = "textiles"
    AGRICULTURE = "agriculture"
    MACHINERY = "machinery"
    PHARMACEUTICALS = "pharmaceuticals"
    CHEMICALS = "chemicals"


class RestrictionLevel(StrEnum):
    """Import-restriction disposition carried by an HTS clause.

    ``classify_import_restriction`` (Phase 3) maps a manifest line to one of these
    by joining on the line's HTS code. ``PROHIBITED`` here means *not admissible
    without a specific exception* — it is distinct from the pre-agent escalation
    guard, which intercepts contraband / sanctions signals before the model runs.
    """

    UNRESTRICTED = "unrestricted"
    LICENSE_REQUIRED = "license_required"
    QUOTA_CONTROLLED = "quota_controlled"
    PROHIBITED = "prohibited"


class ShipmentStatus(StrEnum):
    """Lifecycle state of a shipment in the synthetic manifest store."""

    IN_TRANSIT = "in_transit"
    HELD = "held"
    FLAGGED = "flagged"
    CLEARED = "cleared"


class Vendor(BaseModel):
    """An importer whose scope bounds every tool call made on its behalf."""

    model_config = ConfigDict(frozen=True)

    vendor_id: str = Field(pattern=VENDOR_ID_PATTERN)
    legal_name: str
    country: str
    customs_broker: str
    categories: tuple[GoodsCategory, ...]
    active: bool = True


class ManifestLineItem(BaseModel):
    """A single declared line on a shipment's bill of lading."""

    model_config = ConfigDict(frozen=True)

    line_no: int = Field(ge=1)
    description: str
    hts_code: str
    quantity: int = Field(ge=1)
    unit: str
    declared_value_usd: float = Field(ge=0)
    country_of_origin: str


class Shipment(BaseModel):
    """A vendor-scoped import shipment and its declared manifest."""

    model_config = ConfigDict(frozen=True)

    shipment_id: str = Field(pattern=SHIPMENT_ID_PATTERN)
    vendor_id: str = Field(pattern=VENDOR_ID_PATTERN)
    bill_of_lading: str
    carrier: str
    container_id: str
    origin_port: str
    destination_port: str
    eta: str  # ISO-8601 date (YYYY-MM-DD)
    status: ShipmentStatus
    flag_reason: str | None = None
    manifest: tuple[ManifestLineItem, ...]


class HtsClause(BaseModel):
    """A Harmonized Tariff Schedule clause — one record in the shared KB.

    The KB is public HTS reference text, so it is intentionally *not*
    vendor-partitioned (see CLAUDE.md / Pinecone notes). ``page_content`` is the
    text that gets embedded; ``metadata`` is the structured payload Pinecone stores
    alongside the vector so ``retrieve_tariff_regulation`` can cite a clause by id.
    """

    model_config = ConfigDict(frozen=True)

    hts_code: str
    chapter: int = Field(ge=1, le=99)
    heading: str
    title: str
    category: GoodsCategory
    duty_rate: str
    restriction: RestrictionLevel
    description: str
    notes: str | None = None

    def page_content(self) -> str:
        """Render the human-readable clause text used as the embedding input."""
        lines: list[str] = [
            f"HTS {self.hts_code} — {self.title}",
            f"Chapter {self.chapter}: {self.heading}",
            f"Category: {self.category.value}. Duty rate: {self.duty_rate}. "
            f"Restriction: {self.restriction.value}.",
            "",
            self.description,
        ]
        if self.notes:
            lines.append(f"\nNote: {self.notes}")
        return "\n".join(lines)

    def metadata(self) -> dict[str, str | int]:
        """Structured payload stored beside the vector for citation + filtering."""
        return {
            "hts_code": self.hts_code,
            "chapter": self.chapter,
            "heading": self.heading,
            "title": self.title,
            "category": self.category.value,
            "duty_rate": self.duty_rate,
            "restriction": self.restriction.value,
        }


# --- Agent run domain: classification + audit trace ----------------------------
# These back the agent loop (Phase 3), not the seed data. ``AgentTrace`` is the
# single audit document written per run to ``trade-agent-AgentTraces``.


class InquiryIntent(StrEnum):
    """The intent of an analyst inquiry.

    The first four are *model-classifiable* — the classifier LLM may emit them.
    The last two are *system-injected* by the orchestrator/guards and must never
    be produced by the model (a deterministic guard sets ``cross_vendor_refusal``;
    the loop sets ``iteration_cap_exceeded`` on a no-draft fallback).
    """

    TARIFF_LOOKUP = "tariff_lookup"
    MANIFEST_FLAG_RESOLUTION = "manifest_flag_resolution"
    CLEARANCE_REQUIREMENTS = "clearance_requirements"
    UNKNOWN = "unknown"
    CROSS_VENDOR_REFUSAL = "cross_vendor_refusal"
    ITERATION_CAP_EXCEEDED = "iteration_cap_exceeded"


class TraceDisposition(StrEnum):
    """Lifecycle state of an agent trace.

    The agent only ever writes ``draft`` or ``escalated``; a human reviewer flips
    it to ``approved`` or ``rejected`` via the UI (the mandatory human-handoff).
    """

    DRAFT = "draft"
    ESCALATED = "escalated"
    APPROVED = "approved"
    REJECTED = "rejected"


class ImportClassification(BaseModel):
    """Hybrid classifier output: routing intent + optional advisory HTS proposal.

    ``intent`` routes the loop. When the inquiry describes goods whose HTS code is
    missing/vague/disputed, the classifier may also propose ``proposed_hts_heading``
    and a ``restriction_band`` with a calibrated ``confidence``. The *authoritative*
    band for an already-declared code still comes from the deterministic catalog
    join in ``lookup_shipment_manifest`` — these proposal fields are advisory.
    """

    model_config = ConfigDict(frozen=True)

    intent: InquiryIntent
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    proposed_hts_heading: str | None = None
    restriction_band: RestrictionLevel | None = None


class ToolCallLog(BaseModel):
    """One tool invocation recorded on the run's trace.

    ``input``/``output`` are JSON-scalar dicts (summaries, not raw payloads) so the
    trace stays compact and renderable. Appended to the ambient trace context by
    each tool; persisted as an element of ``AgentTrace.tool_calls``.
    """

    model_config = ConfigDict(frozen=True)

    tool_name: str
    input: dict[str, object]
    output: dict[str, object]
    duration_ms: float = Field(ge=0.0)
    timestamp: str  # ISO-8601


class AgentTrace(BaseModel):
    """The single audit document written per agent run.

    One document per run (doc id = ``trace_id``) with every tool call embedded in
    ``tool_calls`` — the granular audit trail the project commits to, recorded as
    one atomic record rather than a document per call.
    """

    model_config = ConfigDict(frozen=True)

    trace_id: str
    timestamp: str  # ISO-8601 run start
    vendor_id: str = Field(pattern=VENDOR_ID_PATTERN)
    user_inquiry: str
    classification: ImportClassification | None = None
    tool_calls: tuple[ToolCallLog, ...] = ()
    draft_response: str | None = None
    # Whether the draft is a releasable clearance response a human can "Approve & release".
    # False when there is nothing to release: a "cannot provide" refusal or the no-draft
    # fallback, or a lookup that matched no shipment (the model still drafts a "no matching
    # shipments" note). Computed once by the orchestrator (``src.agent``) and projected onto
    # the lean ``AgentResult``; the UI gates the Approve action on it. Defaults ``False`` - the
    # safe direction, so an unknown or pre-existing trace reads as non-releasable.
    draft_actionable: bool = False
    # The model's streamed reasoning (Gemini ``thinking``), accumulated from the run's
    # ``thinking_delta`` events by the streaming runner and persisted for the audit-trail
    # reasoning disclosure. ``None`` on the synchronous path (no deltas) and on the pre-model
    # guard paths (the model never ran); the draft, produced by the draft tool, is the
    # authoritative output, never this advisory text.
    thinking_content: str | None = None
    disposition: TraceDisposition
    model: str
    escalation_reason: str | None = None
    # Aggregate token/latency metadata for the AgentOps surface. The token fields are
    # the *billable* split: on Vertex thinking tokens bill at the OUTPUT rate, so
    # ``output_tokens`` already includes ``thoughts_tokens`` and
    # ``prompt_tokens + output_tokens == total_tokens`` (candidates alone would not
    # reconcile against the total). All four are ``None`` on the no-model guard paths.
    duration_ms: float | None = None
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    thoughts_tokens: int | None = None
    total_tokens: int | None = None
