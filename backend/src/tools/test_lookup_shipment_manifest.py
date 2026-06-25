"""Unit tests for lookup_shipment_manifest.

The Firestore repository functions are monkeypatched. Tests cover the
vendor-scoped happy path, the single-read scope-violation audit, the not-found
path, client-side filtering, HTS enrichment, and the security invariant that the
model-facing schema has no vendor argument.
"""

import pytest

import src.tools.lookup_shipment_manifest as lookup_mod
from src import repository
from src.models import ManifestLineItem, Shipment, ShipmentStatus
from src.tracing.trace_context import trace_context


def _shipment(
    *,
    vendor_id: str = "V-002",
    shipment_id: str = "S-2000",
    status: ShipmentStatus = ShipmentStatus.HELD,
    eta: str = "2026-07-10",
) -> Shipment:
    return Shipment(
        shipment_id=shipment_id,
        vendor_id=vendor_id,
        bill_of_lading="BOL-100000",
        carrier="Maersk Line",
        container_id="TRDU1000000",
        origin_port="Kaohsiung, TW",
        destination_port="Los Angeles, US",
        eta=eta,
        status=status,
        flag_reason="license required" if status is ShipmentStatus.HELD else None,
        manifest=(
            ManifestLineItem(
                line_no=1,
                description="Smartphones",
                hts_code="8517.13.0000",
                quantity=100,
                unit="cartons",
                declared_value_usd=50000.0,
                country_of_origin="Vietnam",
            ),
        ),
    )


def test_own_shipment_by_id_returns_enriched_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repository, "get_shipment", lambda _sid: _shipment(vendor_id="V-002"))

    with trace_context("tr-1", "V-002") as ctx:
        result = lookup_mod.run_lookup_shipment_manifest("V-002", shipment_id="S-2000")

    assert len(result) == 1
    line = result[0]["manifest"][0]  # type: ignore[index]
    assert line["restriction"] == "unrestricted"  # joined from the in-process HTS catalog
    assert line["hts_title"] == "Smartphones"
    assert ctx.tool_calls[0].output["count"] == 1
    assert ctx.tool_calls[0].output["scope_violation"] is False


def test_cross_vendor_by_id_returns_empty_and_flags_violation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The fetched shipment belongs to V-003 but the caller is scoped to V-002.
    monkeypatch.setattr(repository, "get_shipment", lambda _sid: _shipment(vendor_id="V-003"))

    with trace_context("tr-1", "V-002") as ctx:
        result = lookup_mod.run_lookup_shipment_manifest("V-002", shipment_id="S-2000")

    assert result == []
    assert ctx.tool_calls[0].output["scope_violation"] is True
    assert ctx.tool_calls[0].output["attempted_vendor_id"] == "V-003"


def test_missing_shipment_is_empty_without_violation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repository, "get_shipment", lambda _sid: None)

    with trace_context("tr-1", "V-002") as ctx:
        result = lookup_mod.run_lookup_shipment_manifest("V-002", shipment_id="S-9999")

    assert result == []
    assert ctx.tool_calls[0].output["scope_violation"] is False


def test_list_path_applies_status_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        repository,
        "list_shipments_for_vendor",
        lambda _vid: [
            _shipment(shipment_id="S-2000", status=ShipmentStatus.HELD),
            _shipment(shipment_id="S-2001", status=ShipmentStatus.CLEARED),
        ],
    )

    with trace_context("tr-1", "V-002"):
        result = lookup_mod.run_lookup_shipment_manifest("V-002", status="held")

    assert [s["shipment_id"] for s in result] == ["S-2000"]


def test_lookup_tool_hides_vendor_from_the_model() -> None:
    args = lookup_mod.lookup_shipment_manifest.args
    assert "vendor_id" not in args
    assert "runtime" not in args
    assert set(args.keys()) == {"shipment_id", "status", "date_from", "date_to"}
