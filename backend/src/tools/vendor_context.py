"""The runtime context schema bound into the agent at invocation time.

``vendor_id`` is resolved by the backend (auth + dropdown selection, validated
against Firestore) and bound here — it travels in LangGraph's runtime *context*,
never in any tool's model-facing argument schema, so the model has no slot to
inject or override it.
"""

from typing import TypedDict


class VendorContext(TypedDict):
    """Typed runtime context for a single agent run."""

    vendor_id: str
