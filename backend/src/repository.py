"""Firestore data-access layer.

The single place that reads and writes the ``trade-agent-*`` collections. All
functions go through the Firestore client *singleton* in ``src/gcp/client.py`` —
never construct a client here. Documents are keyed by their natural id
(``vendor_id`` / ``shipment_id`` / ``trace_id``).

Vendor scoping note: shipments live in a flat collection keyed by the globally
unique ``shipment_id`` with ``vendor_id`` as a field. That lets ``get_shipment``
fetch any shipment in one read; the *caller* (the vendor-scoped lookup tool)
compares ``vendor_id`` to detect — and audit — cross-vendor access in that same
single read, rather than needing a second unscoped query.
"""

from typing import cast

from google.cloud.firestore_v1.base_document import DocumentSnapshot
from google.cloud.firestore_v1.base_query import FieldFilter
from google.cloud.firestore_v1.collection import CollectionReference
from google.cloud.firestore_v1.query import Query

from src.config import (
    FIRESTORE_SHIPMENTS_COLLECTION,
    FIRESTORE_TRACES_COLLECTION,
    FIRESTORE_VENDORS_COLLECTION,
)
from src.gcp.client import get_firestore_client
from src.models import AgentTrace, Shipment, TraceDisposition, Vendor


def _collection(name: str) -> CollectionReference:
    """Resolve a collection reference off the Firestore singleton."""
    return get_firestore_client().collection(name)


def _get_doc(collection: str, doc_id: str) -> DocumentSnapshot:
    """Fetch a single document snapshot by id.

    The sync client's ``get()`` is typed as a sync/async union; we use the sync
    client exclusively, so narrow it to :class:`DocumentSnapshot` here.
    """
    return cast(DocumentSnapshot, _collection(collection).document(doc_id).get())


# --- Vendors -------------------------------------------------------------------
def get_vendor(vendor_id: str) -> Vendor | None:
    """Fetch a vendor by id, or ``None`` if it does not exist."""
    snapshot = _get_doc(FIRESTORE_VENDORS_COLLECTION, vendor_id)
    if not snapshot.exists:
        return None
    data: dict[str, object] = snapshot.to_dict() or {}
    return Vendor.model_validate(data)


def list_vendors() -> list[Vendor]:
    """List every vendor — backs the analyst's vendor-picker dropdown."""
    return [
        Vendor.model_validate(doc.to_dict() or {})
        for doc in _collection(FIRESTORE_VENDORS_COLLECTION).stream()
    ]


# --- Shipments -----------------------------------------------------------------
def get_shipment(shipment_id: str) -> Shipment | None:
    """Fetch a shipment by id (unscoped). The caller enforces vendor scope."""
    snapshot = _get_doc(FIRESTORE_SHIPMENTS_COLLECTION, shipment_id)
    if not snapshot.exists:
        return None
    return Shipment.model_validate(snapshot.to_dict() or {})


def get_shipment_owner(shipment_id: str) -> str | None:
    """Return the ``vendor_id`` that owns a shipment, or ``None`` if absent.

    Used by the pre-model cross-vendor guard to verify ownership before the agent
    runs. Reads only the owning field rather than validating the full model.
    """
    snapshot = _get_doc(FIRESTORE_SHIPMENTS_COLLECTION, shipment_id)
    if not snapshot.exists:
        return None
    data: dict[str, object] = snapshot.to_dict() or {}
    owner: object = data.get("vendor_id")
    return str(owner) if owner is not None else None


def list_shipments_for_vendor(vendor_id: str) -> list[Shipment]:
    """List every shipment for one vendor — a vendor-scoped query (no cross-vendor)."""
    query: Query = _collection(FIRESTORE_SHIPMENTS_COLLECTION).where(
        filter=FieldFilter("vendor_id", "==", vendor_id)
    )
    return [Shipment.model_validate(doc.to_dict() or {}) for doc in query.stream()]


# --- Agent traces --------------------------------------------------------------
def get_trace(trace_id: str) -> AgentTrace | None:
    """Fetch a single audit trace by id, or ``None`` if it does not exist.

    Backs the scope check on the human-review disposition endpoint: the reviewer may
    only act on a draft whose vendor is within their authorized scope.
    """
    snapshot = _get_doc(FIRESTORE_TRACES_COLLECTION, trace_id)
    if not snapshot.exists:
        return None
    return AgentTrace.model_validate(snapshot.to_dict() or {})


def put_trace(trace: AgentTrace) -> None:
    """Write the single per-run audit document (idempotent on ``trace_id``)."""
    payload: dict[str, object] = trace.model_dump(mode="json")
    _collection(FIRESTORE_TRACES_COLLECTION).document(trace.trace_id).set(payload)


def update_trace_disposition(trace_id: str, disposition: TraceDisposition) -> None:
    """Flip a trace's disposition — the human-review approve/reject action."""
    _collection(FIRESTORE_TRACES_COLLECTION).document(trace_id).update(
        {"disposition": disposition.value}
    )


def list_recent_traces(limit: int) -> list[AgentTrace]:
    """Return the ``limit`` most recent traces, newest first.

    Firestore serves ``order_by + limit`` natively, so this needs no client-side
    sort (unlike a key-value store that would require a secondary index + scan).
    """
    query: Query = (
        _collection(FIRESTORE_TRACES_COLLECTION)
        .order_by("timestamp", direction=Query.DESCENDING)
        .limit(limit)
    )
    return [AgentTrace.model_validate(doc.to_dict() or {}) for doc in query.stream()]
