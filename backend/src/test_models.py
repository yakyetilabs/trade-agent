"""Unit tests for the domain models — validation rules and KB rendering."""

import pytest
from pydantic import ValidationError

from src.models import (
    GoodsCategory,
    HtsClause,
    RestrictionLevel,
    Shipment,
    ShipmentStatus,
    Vendor,
)


def _clause(**overrides: object) -> HtsClause:
    base: dict[str, object] = {
        "hts_code": "8471.30.0100",
        "chapter": 84,
        "heading": "Automatic data-processing machines",
        "title": "Portable digital computers",
        "category": GoodsCategory.ELECTRONICS,
        "duty_rate": "Free",
        "restriction": RestrictionLevel.UNRESTRICTED,
        "description": "Laptop and tablet computers weighing under 10 kg.",
    }
    return HtsClause(**(base | overrides))  # type: ignore[arg-type]


def test_vendor_id_pattern_is_enforced() -> None:
    with pytest.raises(ValidationError):
        Vendor(
            vendor_id="VENDOR-1",  # wrong shape — must be V-\d{3,}
            legal_name="Bad Co",
            country="US",
            customs_broker="Broker",
            categories=(GoodsCategory.ELECTRONICS,),
        )


def test_shipment_id_pattern_is_enforced() -> None:
    with pytest.raises(ValidationError):
        Shipment(
            shipment_id="S-12",  # too short — must be S-\d{4,}
            vendor_id="V-001",
            bill_of_lading="BOL-1",
            carrier="C",
            container_id="CID",
            origin_port="A",
            destination_port="B",
            eta="2026-01-01",
            status=ShipmentStatus.IN_TRANSIT,
            manifest=(),
        )


def test_hts_page_content_includes_code_title_and_description() -> None:
    content = _clause().page_content()
    assert "HTS 8471.30.0100 — Portable digital computers" in content
    assert "Laptop and tablet computers" in content
    assert "Note:" not in content  # no note supplied


def test_hts_page_content_appends_note_when_present() -> None:
    content = _clause(notes="Subject to FCC equipment authorization.").page_content()
    assert "Note: Subject to FCC equipment authorization." in content


def test_hts_metadata_renders_enums_as_plain_strings() -> None:
    meta = _clause(restriction=RestrictionLevel.LICENSE_REQUIRED).metadata()
    assert meta["restriction"] == "license_required"
    assert meta["category"] == "electronics"
    assert meta["hts_code"] == "8471.30.0100"
    # Pinecone metadata values must be JSON scalars, not enum objects.
    assert all(isinstance(v, str | int) for v in meta.values())


def test_models_are_frozen() -> None:
    vendor = Vendor(
        vendor_id="V-001",
        legal_name="Meridian",
        country="TW",
        customs_broker="Broker",
        categories=(GoodsCategory.ELECTRONICS,),
    )
    with pytest.raises(ValidationError):
        vendor.legal_name = "Mutated"  # type: ignore[misc]
