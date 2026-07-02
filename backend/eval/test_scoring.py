"""Unit tests for the deterministic scorer (no model).

Synthetic :class:`~src.agent.AgentResult` objects are scored against hand-built cases to
prove each assertion type passes/fails as specified.
"""

from eval.schema import EvalCase, EvalCategory, Expect
from eval.scoring import score_case
from src.agent import AgentResult
from src.models import ImportClassification, InquiryIntent, TraceDisposition

_DEFAULT_CLASSIFICATION = ImportClassification(
    intent=InquiryIntent.MANIFEST_FLAG_RESOLUTION, confidence=0.9, reasoning="r"
)


def _result(
    *,
    disposition: TraceDisposition = TraceDisposition.DRAFT,
    draft: str | None = "Shipment S-1001 is held pending a license per HTS 8526.10.0040.",
    classification: ImportClassification | None = _DEFAULT_CLASSIFICATION,
    tool_names: tuple[str, ...] = ("classify_import_restriction", "lookup_shipment_manifest"),
    tool_call_count: int | None = None,
    duration_ms: float = 1200.0,
    escalation_reason: str | None = None,
    total_tokens: int | None = 140,
) -> AgentResult:
    return AgentResult(
        trace_id="tr-x",
        disposition=disposition,
        draft_response=draft,
        classification=classification,
        tool_call_count=tool_call_count if tool_call_count is not None else len(tool_names),
        tool_names=list(tool_names),
        duration_ms=duration_ms,
        model="m",
        escalation_reason=escalation_reason,
        total_tokens=total_tokens,
    )


def _case(category: EvalCategory, expect: Expect) -> EvalCase:
    return EvalCase(
        id="t", category=category, vendor_id="V-001", inquiry="x", rationale="x", expect=expect
    )


def test_all_assertions_pass() -> None:
    case = _case(
        EvalCategory.HAPPY_PATH,
        Expect(
            disposition="draft",
            intent_in=("manifest_flag_resolution", "tariff_lookup"),
            tools_called=("classify_import_restriction", "lookup_shipment_manifest"),
            cited_shipment_ids=("S-1001",),
            draft_includes=("8526.10.0040",),
            draft_includes_any=("license", "radar"),
        ),
    )
    score = score_case(_result(), case)
    assert score.passed
    assert score.passed_count == score.total


def test_mismatches_fail_specific_assertions() -> None:
    case = _case(
        EvalCategory.HAPPY_PATH,
        Expect(
            disposition="escalated",  # actual is draft
            tools_called=("retrieve_tariff_regulation",),  # not called
            cited_shipment_ids=("S-9999",),  # not in draft
        ),
    )
    score = score_case(_result(), case)
    assert not score.passed
    failed = {a.name for a in score.assertions if not a.passed}
    assert failed == {"disposition", "tool_called:retrieve_tariff_regulation", "cites:S-9999"}


def test_escalation_result_scores_clean() -> None:
    result = _result(
        disposition=TraceDisposition.ESCALATED,
        draft=None,
        classification=None,
        tool_names=(),
        escalation_reason="contraband",
    )
    case = _case(
        EvalCategory.ESCALATION_TRIGGERS,
        Expect(
            disposition="escalated",
            escalation_reason="contraband",
            classification_present=False,
            max_tool_calls=0,
        ),
    )
    assert score_case(result, case).passed


def test_includes_any_and_excludes() -> None:
    cleared = _result(draft="Shipment S-1002 has cleared customs; there is no hold.")
    passing = _case(
        EvalCategory.HAPPY_PATH,
        Expect(draft_includes_any=("cleared", "not held"), draft_excludes=("seized",)),
    )
    assert score_case(cleared, passing).passed

    failing = _case(
        EvalCategory.HAPPY_PATH,
        Expect(draft_includes_any=("rejected", "denied")),  # neither present
    )
    assert not score_case(cleared, failing).passed
