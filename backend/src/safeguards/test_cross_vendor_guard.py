"""Unit tests for the pre-agent cross-vendor reference guard."""

from src.safeguards.cross_vendor_guard import detect_cross_vendor_reference

# Deterministic ownership fixture for the injected lookup.
_OWNERS: dict[str, str] = {"S-2000": "V-002", "S-3000": "V-003"}


def _owner_lookup(shipment_id: str) -> str | None:
    return _OWNERS.get(shipment_id)


def test_own_vendor_reference_is_allowed() -> None:
    result = detect_cross_vendor_reference(
        "V-002", "Show me the status of V-002 shipments", _owner_lookup
    )
    assert result.is_violation is False


def test_foreign_vendor_reference_is_blocked() -> None:
    result = detect_cross_vendor_reference(
        "V-002", "Show me V-015's most recent shipment", _owner_lookup
    )
    assert result.is_violation is True
    assert result.reason is not None
    assert "V-015" in result.reason


def test_own_shipment_reference_is_allowed() -> None:
    result = detect_cross_vendor_reference(
        "V-002", "What happened with shipment S-2000?", _owner_lookup
    )
    assert result.is_violation is False


def test_foreign_shipment_reference_is_blocked() -> None:
    result = detect_cross_vendor_reference("V-002", "Tell me about shipment S-3000", _owner_lookup)
    assert result.is_violation is True
    assert result.reason is not None
    assert "S-3000" in result.reason


def test_unknown_shipment_is_not_a_violation() -> None:
    # Non-existent shipment → owner None → the scoped lookup tool handles it.
    result = detect_cross_vendor_reference("V-002", "Tell me about shipment S-9999", _owner_lookup)
    assert result.is_violation is False


def test_detection_is_case_insensitive() -> None:
    result = detect_cross_vendor_reference("V-002", "show me v-015 details", _owner_lookup)
    assert result.is_violation is True


def test_no_ids_is_not_a_violation() -> None:
    result = detect_cross_vendor_reference(
        "V-002", "What is my annual duty exposure?", _owner_lookup
    )
    assert result.is_violation is False
