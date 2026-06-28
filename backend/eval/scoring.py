"""Deterministic scorer: an :class:`~src.agent.AgentResult` against an ``EvalCase``.

Pure functions, no I/O — every assertion is a boolean check over the result, so a case's
score is fully reproducible given the agent output. This is the test seam: the harness
tests exercise ``score_case`` with synthetic results and never touch a model.
"""

from dataclasses import dataclass

from eval.schema import EvalCase
from src.agent import AgentResult


@dataclass(frozen=True)
class AssertionResult:
    """One assertion's outcome, with a short detail for the report."""

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class CaseScore:
    """All assertion outcomes for one case under one model."""

    case_id: str
    category: str
    assertions: tuple[AssertionResult, ...]

    @property
    def passed(self) -> bool:
        """A case passes only if every one of its assertions passes."""
        return all(a.passed for a in self.assertions)

    @property
    def total(self) -> int:
        return len(self.assertions)

    @property
    def passed_count(self) -> int:
        return sum(1 for a in self.assertions if a.passed)


def score_case(result: AgentResult, case: EvalCase) -> CaseScore:
    """Check every assertion the case declares against the agent's result."""
    expect = case.expect
    checks: list[AssertionResult] = []

    def add(name: str, passed: bool, detail: str = "") -> None:
        checks.append(AssertionResult(name=name, passed=passed, detail=detail))

    draft = (result.draft_response or "").lower()
    intent = result.classification.intent.value if result.classification is not None else None

    if expect.disposition is not None:
        add(
            "disposition",
            result.disposition.value == expect.disposition,
            f"got={result.disposition.value}",
        )
    if expect.escalation_reason is not None:
        add(
            "escalation_reason",
            result.escalation_reason == expect.escalation_reason,
            f"got={result.escalation_reason}",
        )
    if expect.intent_in is not None:
        add("intent_in", intent in expect.intent_in, f"got={intent}")
    if expect.classification_present is not None:
        add(
            "classification_present",
            (result.classification is not None) == expect.classification_present,
            f"got={result.classification is not None}",
        )
    for tool in expect.tools_called:
        add(f"tool_called:{tool}", tool in result.tool_names, f"tools={result.tool_names}")
    for tool in expect.tools_absent:
        add(f"tool_absent:{tool}", tool not in result.tool_names, f"tools={result.tool_names}")
    if expect.max_tool_calls is not None:
        add(
            "max_tool_calls",
            result.tool_call_count <= expect.max_tool_calls,
            f"got={result.tool_call_count}",
        )
    for sid in expect.cited_shipment_ids:
        add(f"cites:{sid}", sid.lower() in draft)
    for needle in expect.draft_includes:
        add(f"includes:{needle}", needle.lower() in draft)
    if expect.draft_includes_any:
        add(
            "includes_any",
            any(n.lower() in draft for n in expect.draft_includes_any),
            f"any_of={list(expect.draft_includes_any)}",
        )
    for needle in expect.draft_excludes:
        add(f"excludes:{needle}", needle.lower() not in draft)
    if expect.max_duration_ms is not None:
        add(
            "max_duration_ms",
            result.duration_ms <= expect.max_duration_ms,
            f"got={result.duration_ms:.0f}ms",
        )

    return CaseScore(case_id=case.id, category=case.category.value, assertions=tuple(checks))
