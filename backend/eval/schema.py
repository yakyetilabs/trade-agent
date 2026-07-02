"""Eval case schema + loader.

A case is a set of *optional* assertions over an :class:`~src.agent.AgentResult`. Each
case declares only the assertions relevant to it; the scorer (``scoring.py``) checks the
ones present. Assertions lean on orchestrator-deterministic signals (disposition,
escalation reason, injected intents, tool-call count) so guard/scope/escalation cases
score identically across models; the model-dependent signals (cited ids, draft phrasing)
are the quality axis the Haiku-vs-Sonnet comparison actually measures.

Grounding — that every cited shipment id is a real generated shipment owned by the
case's vendor — is enforced by the co-located ``test_schema.py`` against the synthetic
generators, so the suite can never drift from the seed data.
"""

import json
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

_CASES_PATH = Path(__file__).parent / "cases.json"


class EvalCategory(StrEnum):
    """The four curated categories (mirrors DESIGN_DECISIONS.md §6) - one per
    load-bearing system property: the grounded pipeline, the exact-fetch retrieval
    mode, and the two deterministic pre-model guards."""

    HAPPY_PATH = "happy_path"
    EXACT_HTS_FETCH = "exact_hts_fetch"
    ESCALATION_TRIGGERS = "escalation_triggers"
    SCOPE_VIOLATIONS = "scope_violations"


class Expect(BaseModel):
    """The assertions a case makes about the agent's result. All optional.

    String matches (``draft_*``) are case-insensitive substring tests. ``draft_includes``
    and ``cited_shipment_ids`` require *all* listed substrings; ``draft_includes_any``
    passes if *any* is present (for traps where correct phrasing varies); ``draft_excludes``
    requires *none* (the hallucination guard).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    disposition: str | None = None  # "draft" | "escalated"
    escalation_reason: str | None = None  # guard category, e.g. "contraband"
    intent_in: tuple[str, ...] | None = None  # classification.intent must be one of these
    classification_present: bool | None = None
    tools_called: tuple[str, ...] = ()  # all of these tool names must appear
    tools_absent: tuple[str, ...] = ()  # none of these may appear
    max_tool_calls: int | None = None  # e.g. 0 — model never ran (guard short-circuit)
    cited_shipment_ids: tuple[str, ...] = ()  # all must appear in the draft (grounding)
    draft_includes: tuple[str, ...] = ()  # all must appear
    draft_includes_any: tuple[str, ...] = ()  # at least one must appear
    draft_excludes: tuple[str, ...] = ()  # none may appear (anti-hallucination)
    max_duration_ms: float | None = None  # soft latency bound


class EvalCase(BaseModel):
    """One grounded evaluation case."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    category: EvalCategory
    vendor_id: str
    inquiry: str
    rationale: str  # why this case exists / what it proves — doubles as showcase narrative
    expect: Expect


def load_cases(path: Path | None = None) -> list[EvalCase]:
    """Load and validate the version-controlled case suite from ``cases.json``."""
    raw: list[dict[str, object]] = json.loads((path or _CASES_PATH).read_text())
    return [EvalCase.model_validate(case) for case in raw]
