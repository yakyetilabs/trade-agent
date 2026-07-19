"""The runtime context schema bound into the agent at invocation time.

Both fields are resolved by the backend and bound here - they travel in LangGraph's
runtime *context*, never in any tool's model-facing argument schema, so the model has
no slot to inject or override them:

- ``vendor_id``: the run's authorized vendor scope (auth + dropdown selection,
  validated against Firestore).
- ``model_id``: the run's concrete chat-model binding. The serving path always binds
  the primary model; the eval runner overrides it per comparison arm, and any tool
  that makes its own internal model call (the classifier's structured-output call)
  must read the binding from here so an eval arm is measured end to end on one model.
"""

from typing import TypedDict


class VendorContext(TypedDict):
    """Typed runtime context for a single agent run."""

    vendor_id: str
    model_id: str
