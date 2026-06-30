"""Shared in-process HTS clause index (HTS code -> clause), built once at import.

Two deterministic paths join an HTS code to its authoritative clause: manifest
line enrichment in ``lookup_shipment_manifest`` and the exact-fetch path in
``retrieve_tariff_regulation``. Both read this single index rather than each
building its own copy of the same dict.

The same clauses also live in Pinecone as embedded vectors for the semantic
retrieve path - a deliberate double-storage discussed in the Retrieval section
(§8) of ``docs/DESIGN_DECISIONS.md``.
"""

from src.data.generators import build_hts_clauses
from src.models import HtsClause

# Built once at import: HTS code -> clause.
_HTS_INDEX: dict[str, HtsClause] = {clause.hts_code: clause for clause in build_hts_clauses()}


def get_hts_clause(hts_code: str) -> HtsClause | None:
    """Return the catalog clause for an exact HTS code, or ``None`` if not present."""
    return _HTS_INDEX.get(hts_code)
