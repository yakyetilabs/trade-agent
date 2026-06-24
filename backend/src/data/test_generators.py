"""Invariant tests for the synthetic data generators.

These lock the properties the seed/ingest scripts and downstream tools rely on:
determinism, vendor scoping, id shapes that match the cross-vendor guard patterns,
and consistency between a shipment's status and its flag reason.
"""

import re

from src.data.generators import (
    DEFAULT_SEED,
    build_hts_clauses,
    build_shipments,
    build_vendors,
)
from src.models import (
    SHIPMENT_ID_PATTERN,
    VENDOR_ID_PATTERN,
    RestrictionLevel,
    ShipmentStatus,
)


def test_vendors_have_unique_ids_matching_pattern() -> None:
    vendors = build_vendors()
    ids = [v.vendor_id for v in vendors]
    assert len(ids) == len(set(ids))
    assert all(re.match(VENDOR_ID_PATTERN, vid) for vid in ids)


def test_hts_clauses_have_unique_codes() -> None:
    clauses = build_hts_clauses()
    codes = [c.hts_code for c in clauses]
    assert len(codes) == len(set(codes))
    assert len(clauses) >= 20  # enough corpus to make retrieval meaningful


def test_hts_catalog_covers_a_prohibited_and_license_required_clause() -> None:
    restrictions = {c.restriction for c in build_hts_clauses()}
    # The classifier + escalation demos need at least these bands present.
    assert RestrictionLevel.PROHIBITED in restrictions
    assert RestrictionLevel.LICENSE_REQUIRED in restrictions
    assert RestrictionLevel.QUOTA_CONTROLLED in restrictions


def test_shipment_generation_is_deterministic() -> None:
    assert build_shipments(DEFAULT_SEED) == build_shipments(DEFAULT_SEED)


def test_different_seed_changes_output() -> None:
    assert build_shipments(DEFAULT_SEED) != build_shipments(DEFAULT_SEED + 1)


def test_shipment_ids_are_unique_and_match_pattern() -> None:
    shipments = build_shipments()
    ids = [s.shipment_id for s in shipments]
    assert len(ids) == len(set(ids))
    assert all(re.match(SHIPMENT_ID_PATTERN, sid) for sid in ids)


def test_every_shipment_is_scoped_to_a_known_vendor_and_its_categories() -> None:
    vendors_by_id = {v.vendor_id: v for v in build_vendors()}
    clauses_by_code = {c.hts_code: c for c in build_hts_clauses()}

    for shipment in build_shipments():
        vendor = vendors_by_id[shipment.vendor_id]  # KeyError if unscoped
        assert shipment.manifest, "every shipment carries at least one manifest line"
        for line in shipment.manifest:
            clause = clauses_by_code[line.hts_code]  # KeyError if code is fabricated
            assert clause.category in vendor.categories


def test_status_and_flag_reason_are_consistent() -> None:
    for shipment in build_shipments():
        if shipment.status in (ShipmentStatus.HELD, ShipmentStatus.FLAGGED):
            assert shipment.flag_reason is not None
        else:
            assert shipment.flag_reason is None
