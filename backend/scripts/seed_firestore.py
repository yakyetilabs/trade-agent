"""Seed Firestore with the synthetic vendors and shipments.

Writes the curated vendor catalog and the deterministically generated shipments
into their ``trade-agent-*`` collections, using each record's natural id as the
document id (``vendor_id`` / ``shipment_id``). Writes are idempotent: re-running
overwrites the same documents rather than duplicating them.

Usage (from ``backend/``):

    uv run python -m scripts.seed_firestore            # write to Firestore
    uv run python -m scripts.seed_firestore --dry-run  # print plan, no writes
    uv run python -m scripts.seed_firestore --seed 7   # alternate shipment seed

Requires Google credentials (``GOOGLE_APPLICATION_CREDENTIALS`` locally, or the
attached service account on Cloud Run). ``--dry-run`` needs neither.
"""

import argparse
from collections.abc import Iterable, Sequence

from pydantic import BaseModel

from src.config import (
    FIRESTORE_SHIPMENTS_COLLECTION,
    FIRESTORE_VENDORS_COLLECTION,
    GCP_PROJECT,
)
from src.data.generators import DEFAULT_SEED, build_shipments, build_vendors
from src.gcp.client import get_firestore_client

# Firestore caps a single batched write at 500 operations; chunk well under it.
_BATCH_LIMIT: int = 400


def _chunks[T](items: Sequence[T], size: int) -> Iterable[Sequence[T]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _seed_collection(
    collection: str,
    records: Sequence[BaseModel],
    id_field: str,
    *,
    dry_run: bool,
) -> int:
    """Idempotently write ``records`` into ``collection`` keyed by ``id_field``."""
    if dry_run:
        for record in records:
            doc_id = getattr(record, id_field)
            print(f"  [dry-run] {collection}/{doc_id}")
        return len(records)

    client = get_firestore_client()
    written = 0
    for chunk in _chunks(records, _BATCH_LIMIT):
        batch = client.batch()
        for record in chunk:
            doc_id: str = getattr(record, id_field)
            ref = client.collection(collection).document(doc_id)
            batch.set(ref, record.model_dump(mode="json"))
        batch.commit()
        written += len(chunk)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Firestore with synthetic data.")
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"RNG seed for shipment generation (default: {DEFAULT_SEED}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written without touching Firestore.",
    )
    args = parser.parse_args()

    vendors = build_vendors()
    shipments = build_shipments(args.seed)

    mode = "DRY RUN — no writes" if args.dry_run else f"project={GCP_PROJECT}"
    print(f"Seeding Firestore ({mode})")

    vendor_count = _seed_collection(
        FIRESTORE_VENDORS_COLLECTION, vendors, "vendor_id", dry_run=args.dry_run
    )
    shipment_count = _seed_collection(
        FIRESTORE_SHIPMENTS_COLLECTION, shipments, "shipment_id", dry_run=args.dry_run
    )

    print(
        f"Done: {vendor_count} vendor(s) -> {FIRESTORE_VENDORS_COLLECTION}, "
        f"{shipment_count} shipment(s) -> {FIRESTORE_SHIPMENTS_COLLECTION}."
    )


if __name__ == "__main__":
    main()
