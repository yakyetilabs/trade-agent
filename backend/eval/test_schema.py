"""Suite-integrity + grounding tests for the eval cases.

These run hermetically (no model): they validate that ``cases.json`` parses, keeps the
curated shape (the 4x3 core grid plus two single-case retrieval probes, 14 cases total),
has unique ids, and - critically - that every cited shipment is a real generated shipment
owned by the case's vendor. That last check makes it impossible for the suite to silently
drift away from the synthetic seed data.
"""

from collections import Counter

from eval.schema import EvalCategory, load_cases
from src.data.generators import build_shipments, build_vendors


def test_suite_matches_the_curated_shape() -> None:
    """The curation contract: the 4x3 core grid plus the two single-case retrieval probes
    (semantic discovery accuracy, unsupported-response detection) - 14 cases total."""
    cases = load_cases()
    assert len(cases) == 14
    assert Counter(c.category for c in cases) == {
        EvalCategory.HAPPY_PATH: 3,
        EvalCategory.EXACT_HTS_FETCH: 3,
        EvalCategory.ESCALATION_TRIGGERS: 3,
        EvalCategory.SCOPE_VIOLATIONS: 3,
        EvalCategory.SEMANTIC_RETRIEVAL: 1,
        EvalCategory.UNSUPPORTED_RESPONSE: 1,
    }


def test_case_ids_are_unique() -> None:
    ids = [c.id for c in load_cases()]
    assert len(ids) == len(set(ids))


def test_cases_are_grounded_in_generated_data() -> None:
    vendors = {v.vendor_id for v in build_vendors()}
    shipments = {s.shipment_id: s for s in build_shipments()}
    for case in load_cases():
        assert case.vendor_id in vendors, f"{case.id}: unknown vendor {case.vendor_id}"
        for sid in case.expect.cited_shipment_ids:
            assert sid in shipments, f"{case.id}: cites unknown shipment {sid}"
            assert shipments[sid].vendor_id == case.vendor_id, (
                f"{case.id}: cites {sid} owned by {shipments[sid].vendor_id}, not {case.vendor_id}"
            )


def test_escalation_cases_assert_model_never_ran() -> None:
    for case in load_cases():
        if (
            case.category is EvalCategory.ESCALATION_TRIGGERS
            and case.expect.disposition == "escalated"
        ):
            assert case.expect.max_tool_calls == 0, case.id
            assert case.expect.classification_present is False, case.id
            assert case.expect.escalation_reason is not None, case.id


def test_scope_cases_expect_deterministic_refusal() -> None:
    for case in load_cases():
        if case.category is EvalCategory.SCOPE_VIOLATIONS:
            assert case.expect.intent_in == ("cross_vendor_refusal",), case.id
            assert case.expect.max_tool_calls == 0, case.id
