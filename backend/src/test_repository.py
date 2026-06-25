"""Unit tests for the Firestore repository.

The Firestore client singleton is monkeypatched with a ``MagicMock`` so these
tests exercise the mapping logic (dict <-> model, scope-field reads, write
payloads) hermetically — no real Firestore, no credentials, no network.
"""

from unittest.mock import MagicMock

import pytest

from src import repository
from src.models import AgentTrace, Shipment, TraceDisposition, Vendor

_VENDOR_DICT: dict[str, object] = {
    "vendor_id": "V-001",
    "legal_name": "Meridian Components LLC",
    "country": "Taiwan",
    "customs_broker": "Pacific Rim Customs Brokerage",
    "categories": ["electronics"],
    "active": True,
}

_SHIPMENT_DICT: dict[str, object] = {
    "shipment_id": "S-1001",
    "vendor_id": "V-002",
    "bill_of_lading": "BOL-123456",
    "carrier": "Maersk Line",
    "container_id": "TRDU1234567",
    "origin_port": "Kaohsiung, TW",
    "destination_port": "Los Angeles, US",
    "eta": "2026-07-01",
    "status": "held",
    "flag_reason": "license required",
    "manifest": [
        {
            "line_no": 1,
            "description": "Smartphones",
            "hts_code": "8517.13.0000",
            "quantity": 100,
            "unit": "cartons",
            "declared_value_usd": 50000.0,
            "country_of_origin": "Vietnam",
        }
    ],
}


def _snapshot(*, exists: bool, data: dict[str, object] | None = None) -> MagicMock:
    snap = MagicMock()
    snap.exists = exists
    snap.to_dict.return_value = data
    return snap


def _patch_client(monkeypatch: pytest.MonkeyPatch, client: MagicMock) -> None:
    monkeypatch.setattr(repository, "get_firestore_client", lambda: client)


def test_get_vendor_maps_document_to_model(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client.collection.return_value.document.return_value.get.return_value = _snapshot(
        exists=True, data=_VENDOR_DICT
    )
    _patch_client(monkeypatch, client)

    vendor = repository.get_vendor("V-001")
    assert isinstance(vendor, Vendor)
    assert vendor.vendor_id == "V-001"


def test_get_vendor_returns_none_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client.collection.return_value.document.return_value.get.return_value = _snapshot(exists=False)
    _patch_client(monkeypatch, client)

    assert repository.get_vendor("V-404") is None


def test_get_shipment_owner_reads_vendor_field(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client.collection.return_value.document.return_value.get.return_value = _snapshot(
        exists=True, data={"vendor_id": "V-002"}
    )
    _patch_client(monkeypatch, client)

    assert repository.get_shipment_owner("S-1001") == "V-002"


def test_get_shipment_owner_none_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client.collection.return_value.document.return_value.get.return_value = _snapshot(exists=False)
    _patch_client(monkeypatch, client)

    assert repository.get_shipment_owner("S-9999") is None


def test_list_shipments_for_vendor_maps_and_scopes(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    where = client.collection.return_value.where
    where.return_value.stream.return_value = [_snapshot(exists=True, data=_SHIPMENT_DICT)]
    _patch_client(monkeypatch, client)

    shipments = repository.list_shipments_for_vendor("V-002")
    assert len(shipments) == 1
    assert isinstance(shipments[0], Shipment)
    assert shipments[0].vendor_id == "V-002"
    where.assert_called_once()  # a vendor-scoped filter was applied


def test_put_trace_writes_json_payload_keyed_by_trace_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    _patch_client(monkeypatch, client)
    trace = AgentTrace(
        trace_id="tr-1",
        timestamp="2026-06-25T00:00:00Z",
        vendor_id="V-001",
        user_inquiry="x",
        disposition=TraceDisposition.DRAFT,
        model="gemini-2.5-flash",
    )

    repository.put_trace(trace)

    document = client.collection.return_value.document
    document.assert_called_once_with("tr-1")
    payload = document.return_value.set.call_args.args[0]
    assert payload["trace_id"] == "tr-1"
    assert payload["disposition"] == "draft"  # enum serialized to a plain string


def test_update_trace_disposition_updates_single_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    _patch_client(monkeypatch, client)

    repository.update_trace_disposition("tr-1", TraceDisposition.APPROVED)

    document = client.collection.return_value.document
    document.assert_called_once_with("tr-1")
    document.return_value.update.assert_called_once_with({"disposition": "approved"})


def test_list_recent_traces_orders_and_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    newer = AgentTrace(
        trace_id="tr-new",
        timestamp="2026-06-25T02:00:00Z",
        vendor_id="V-001",
        user_inquiry="x",
        disposition=TraceDisposition.DRAFT,
        model="gemini-2.5-flash",
    )
    older = newer.model_copy(update={"trace_id": "tr-old", "timestamp": "2026-06-25T01:00:00Z"})

    client = MagicMock()
    order_by = client.collection.return_value.order_by
    order_by.return_value.limit.return_value.stream.return_value = [
        _snapshot(exists=True, data=newer.model_dump(mode="json")),
        _snapshot(exists=True, data=older.model_dump(mode="json")),
    ]
    _patch_client(monkeypatch, client)

    traces = repository.list_recent_traces(50)
    assert [t.trace_id for t in traces] == ["tr-new", "tr-old"]
    order_by.assert_called_once()
    order_by.return_value.limit.assert_called_once_with(50)
