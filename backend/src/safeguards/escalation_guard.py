"""Pre-agent escalation guard.

Deterministic, model-free interception of inquiries that must never reach the
LLM. Severe trade-security signals — contraband, OFAC/sanctions, active federal
seizures, and bribery — are routed straight to a human escalation queue *before*
the agent loop runs. The model is not the first line of defense for these.

This is distinct from a *restricted import*. A license-required or even
``prohibited`` HTS band (e.g. a List I chemical precursor) is a routine
compliance case the agent is designed to analyze and draft a response for —
those do **not** escalate here. Escalation is reserved for criminal/security
signals where a model is the wrong first responder.

Rules are intentionally narrow: a false positive routes a legitimate inquiry
away from the agent and degrades the demo. String patterns match
case-insensitively as substrings; compiled regex patterns are used for short
tokens that need word boundaries (so "bribe" does not fire inside another word).
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TriggerRule:
    """A curated escalation category and the patterns that trip it."""

    category: str
    patterns: tuple[str | re.Pattern[str], ...]


@dataclass(frozen=True)
class EscalationDecision:
    """Outcome of the guard: whether to escalate and the matched category."""

    escalate: bool
    reason: str | None


_TRIGGER_RULES: tuple[TriggerRule, ...] = (
    TriggerRule(
        category="contraband",
        patterns=(
            "smuggle",
            "smuggling",
            "narcotics",
            "cocaine",
            "heroin",
            "methamphetamine",
            "illegal drugs",
            "contraband",
            "counterfeit currency",
            "undeclared firearms",
            "unregistered firearms",
            "weapons cache",
            "arms trafficking",
            "human trafficking",
            "ivory tusks",
        ),
    ),
    TriggerRule(
        category="sanctions",
        patterns=(
            "ofac",
            "sdn list",
            "specially designated national",
            "sanctioned entity",
            "sanctioned party",
            "sanctions list",
            "denied party",
            "embargo",
            "embargoed",
        ),
    ),
    TriggerRule(
        category="federal-seizure",
        patterns=(
            "federal seizure",
            "structural seizure",
            "seized by customs",
            "cbp seizure",
            "asset forfeiture",
            "criminal seizure",
            "under criminal investigation",
        ),
    ),
    TriggerRule(
        category="bribery",
        patterns=(
            re.compile(r"\bbrib(?:e|ed|ing|ery)\b", re.IGNORECASE),
            "kickback",
            "grease payment",
            "facilitation payment",
            "pay off the inspector",
            "under the table",
        ),
    ),
)


def should_escalate(inquiry: str) -> EscalationDecision:
    """Return the first matching escalation category, or a no-escalate decision.

    Does not call any model. Returns the matched *category* (a stable, indexable
    audit value) rather than a verbose reason string.
    """
    normalized = inquiry.lower()
    for rule in _TRIGGER_RULES:
        for pattern in rule.patterns:
            matched = (
                bool(pattern.search(inquiry))
                if isinstance(pattern, re.Pattern)
                else pattern.lower() in normalized
            )
            if matched:
                return EscalationDecision(escalate=True, reason=rule.category)
    return EscalationDecision(escalate=False, reason=None)
