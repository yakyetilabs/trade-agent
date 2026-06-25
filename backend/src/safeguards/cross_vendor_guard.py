"""Pre-agent cross-vendor reference guard.

The second deterministic guard (runs after the escalation guard, before the
model). It scans the inquiry for vendor ids (``V-###``) and shipment/bill-of-
lading ids (``S-####``); if any references an ecosystem other than the
authenticated vendor's, the run short-circuits with a refusal and the LLM is
never invoked.

- A directly named *foreign vendor id* fails immediately (no lookup needed).
- A *shipment id* is verified against Firestore ownership via the injected
  ``owner_lookup`` (so the guard stays unit-testable without a live client). A
  shipment that does not exist is not a violation — the scoped lookup tool will
  simply return nothing.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

# Scan patterns (unanchored, case-insensitive) — distinct from the anchored
# full-string validation patterns on the models.
_VENDOR_REF = re.compile(r"\bV-\d{3,}\b", re.IGNORECASE)
_SHIPMENT_REF = re.compile(r"\bS-\d{4,}\b", re.IGNORECASE)


@dataclass(frozen=True)
class CrossVendorDecision:
    """Outcome of the guard: whether a cross-vendor reference was found."""

    is_violation: bool
    reason: str | None


def detect_cross_vendor_reference(
    authenticated_vendor_id: str,
    inquiry: str,
    owner_lookup: Callable[[str], str | None],
) -> CrossVendorDecision:
    """Detect a reference to another vendor's ecosystem in the inquiry text."""
    authenticated = authenticated_vendor_id.upper()

    for match in _VENDOR_REF.findall(inquiry):
        referenced = match.upper()
        if referenced != authenticated:
            reason = (
                f"Inquiry references vendor {referenced}, which is not the authenticated vendor."
            )
            return CrossVendorDecision(is_violation=True, reason=reason)

    for match in _SHIPMENT_REF.findall(inquiry):
        shipment_id = match.upper()
        owner = owner_lookup(shipment_id)
        if owner is not None and owner.upper() != authenticated:
            reason = f"Shipment {shipment_id} belongs to a different vendor."
            return CrossVendorDecision(is_violation=True, reason=reason)

    return CrossVendorDecision(is_violation=False, reason=None)
