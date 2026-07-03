"""Unit tests for the domain models — validation rules and KB rendering."""

import pytest
from pydantic import ValidationError

from src.models import (
    AgentTrace,
    GoodsCategory,
    HtsClause,
    ImportClassification,
    InquiryIntent,
    RestrictionLevel,
    Shipment,
    ShipmentStatus,
    ToolCallLog,
    TraceDisposition,
    Vendor,
)


def _clause(**overrides: object) -> HtsClause:
    base: dict[str, object] = {
        "hts_code": "8471.30.0100",
        "chapter": 84,
        "heading": "Automatic data-processing machines",
        "title": "Portable digital computers",
        "category": GoodsCategory.ELECTRONICS,
        "duty_rate": "Free",
        "restriction": RestrictionLevel.UNRESTRICTED,
        "description": "Laptop and tablet computers weighing under 10 kg.",
    }
    return HtsClause(**(base | overrides))  # type: ignore[arg-type]


def test_vendor_id_pattern_is_enforced() -> None:
    with pytest.raises(ValidationError):
        Vendor(
            vendor_id="VENDOR-1",  # wrong shape — must be V-\d{3,}
            legal_name="Bad Co",
            country="US",
            customs_broker="Broker",
            categories=(GoodsCategory.ELECTRONICS,),
        )


def test_shipment_id_pattern_is_enforced() -> None:
    with pytest.raises(ValidationError):
        Shipment(
            shipment_id="S-12",  # too short — must be S-\d{4,}
            vendor_id="V-001",
            bill_of_lading="BOL-1",
            carrier="C",
            container_id="CID",
            origin_port="A",
            destination_port="B",
            eta="2026-01-01",
            status=ShipmentStatus.IN_TRANSIT,
            manifest=(),
        )


def test_hts_page_content_includes_code_title_and_description() -> None:
    content = _clause().page_content()
    assert "HTS 8471.30.0100 — Portable digital computers" in content
    assert "Laptop and tablet computers" in content
    assert "Note:" not in content  # no note supplied


def test_hts_page_content_appends_note_when_present() -> None:
    content = _clause(notes="Subject to FCC equipment authorization.").page_content()
    assert "Note: Subject to FCC equipment authorization." in content


def test_hts_metadata_renders_enums_as_plain_strings() -> None:
    meta = _clause(restriction=RestrictionLevel.LICENSE_REQUIRED).metadata()
    assert meta["restriction"] == "license_required"
    assert meta["category"] == "electronics"
    assert meta["hts_code"] == "8471.30.0100"
    # Pinecone metadata values must be JSON scalars, not enum objects.
    assert all(isinstance(v, str | int) for v in meta.values())


def test_models_are_frozen() -> None:
    vendor = Vendor(
        vendor_id="V-001",
        legal_name="Meridian",
        country="TW",
        customs_broker="Broker",
        categories=(GoodsCategory.ELECTRONICS,),
    )
    with pytest.raises(ValidationError):
        vendor.legal_name = "Mutated"  # type: ignore[misc]


def test_classification_confidence_is_bounded() -> None:
    with pytest.raises(ValidationError):
        ImportClassification(
            intent=InquiryIntent.TARIFF_LOOKUP, confidence=1.5, reasoning="too high"
        )


def test_classification_proposal_fields_default_to_none() -> None:
    clf = ImportClassification(
        intent=InquiryIntent.MANIFEST_FLAG_RESOLUTION,
        confidence=0.9,
        reasoning="flagged line",
    )
    assert clf.proposed_hts_heading is None
    assert clf.restriction_band is None


def test_agent_trace_round_trips_through_json_dump() -> None:
    trace = AgentTrace(
        trace_id="tr-123",
        timestamp="2026-06-25T00:00:00Z",
        vendor_id="V-002",
        user_inquiry="Why is my shipment held?",
        classification=ImportClassification(
            intent=InquiryIntent.MANIFEST_FLAG_RESOLUTION,
            confidence=0.88,
            reasoning="references a held shipment",
        ),
        tool_calls=(
            ToolCallLog(
                tool_name="lookup_shipment_manifest",
                input={"shipment_id": "S-1001"},
                output={"count": 1, "scope_violation": False},
                duration_ms=12.5,
                timestamp="2026-06-25T00:00:01Z",
            ),
        ),
        draft_response="Draft text.",
        draft_actionable=True,
        disposition=TraceDisposition.DRAFT,
        model="gemini-2.5-flash",
    )
    dumped = trace.model_dump(mode="json")
    # Enums serialize to plain strings; nested models to dicts; tuples to lists.
    assert dumped["disposition"] == "draft"
    assert dumped["classification"]["intent"] == "manifest_flag_resolution"
    assert isinstance(dumped["tool_calls"], list)
    assert dumped["tool_calls"][0]["tool_name"] == "lookup_shipment_manifest"
    assert dumped["draft_actionable"] is True
    # And it validates back into an equal model.
    assert AgentTrace.model_validate(dumped) == trace


def test_agent_trace_rejects_malformed_vendor_id() -> None:
    with pytest.raises(ValidationError):
        AgentTrace(
            trace_id="tr-1",
            timestamp="2026-06-25T00:00:00Z",
            vendor_id="VENDOR-2",  # must match V-\d{3,}
            user_inquiry="x",
            disposition=TraceDisposition.ESCALATED,
            model="gemini-2.5-flash",
        )


def test_agent_trace_thinking_content_defaults_none() -> None:
    """thinking_content is optional — None on the synchronous and pre-model-guard paths."""
    trace = AgentTrace(
        trace_id="tr-think",
        timestamp="2026-06-25T00:00:00Z",
        vendor_id="V-003",
        user_inquiry="Why is my shipment held?",
        disposition=TraceDisposition.DRAFT,
        model="gemini-2.5-flash",
    )
    assert trace.thinking_content is None


def test_agent_trace_draft_actionable_defaults_false() -> None:
    """draft_actionable defaults False - the safe direction, so an unset or legacy trace
    reads as non-releasable rather than offering Approve on an unknown result."""
    trace = AgentTrace(
        trace_id="tr-act",
        timestamp="2026-06-25T00:00:00Z",
        vendor_id="V-003",
        user_inquiry="Why is my shipment held?",
        disposition=TraceDisposition.DRAFT,
        model="gemini-2.5-flash",
    )
    assert trace.draft_actionable is False


def test_agent_trace_persists_thinking_content_through_json_dump() -> None:
    """The streamed reasoning round-trips through the Firestore JSON dump."""
    trace = AgentTrace(
        trace_id="tr-think",
        timestamp="2026-06-25T00:00:00Z",
        vendor_id="V-003",
        user_inquiry="Why is my shipment held?",
        draft_response="Draft text.",
        thinking_content="Reviewing S-1001 against HTS 8517.13.0000.",
        disposition=TraceDisposition.DRAFT,
        model="gemini-2.5-flash",
    )
    dumped = trace.model_dump(mode="json")
    assert dumped["thinking_content"] == "Reviewing S-1001 against HTS 8517.13.0000."
    assert AgentTrace.model_validate(dumped) == trace
