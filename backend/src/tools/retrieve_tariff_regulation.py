"""Tool 3: retrieve_tariff_regulation - merge an exact HTS-code fetch with dense
search over the shared, intentionally non-vendor-partitioned HTS knowledge base.

Design rationale and the deferred reranker threshold: see the Retrieval section
(§8) in ``docs/DESIGN_DECISIONS.md``.
"""

import re
from functools import lru_cache

from langchain_core.documents import Document
from langchain_core.tools import tool
from langchain_pinecone import PineconeVectorStore

from src.config import PINECONE_API_KEY, PINECONE_INDEX
from src.data.hts_catalog import get_hts_clause
from src.embeddings import VertexEmbeddings
from src.models import HtsClause
from src.tracing.trace_context import record_tool_call

_DEFAULT_K = 5

# Full HTS clause-id only (4.2.4 digits, e.g. 8517.13.0000); partial or
# heading-level codes fall through to the dense path.
_HTS_CODE_PATTERN = re.compile(r"\d{4}\.\d{2}\.\d{4}")

# Sentinel score for an exact catalog fetch: a deterministic id match has no
# cosine similarity, so the `match` field is the real exact-vs-semantic flag.
_EXACT_MATCH_SCORE = 1.0


@lru_cache(maxsize=1)
def _vector_store() -> PineconeVectorStore:
    """Construct the Pinecone-backed vector store once (Vertex embeds, Pinecone stores)."""
    return PineconeVectorStore(
        index_name=PINECONE_INDEX,
        pinecone_api_key=PINECONE_API_KEY,
        embedding=VertexEmbeddings(),
    )


def _similarity_search(query: str, k: int) -> list[tuple[Document, float]]:
    """Run the vector search - the test seam for this tool."""
    return _vector_store().similarity_search_with_score(query, k=k)


def _to_chunk(document: Document, score: float) -> dict[str, object]:
    """Normalize a dense vector hit into the stable chunk shape."""
    metadata: dict[str, object] = dict(document.metadata or {})
    return {
        "hts_code": metadata.get("hts_code"),
        "title": metadata.get("title"),
        "restriction": metadata.get("restriction"),
        "duty_rate": metadata.get("duty_rate"),
        "content": document.page_content,
        "score": score,
        "match": "semantic",
    }


def _clause_to_chunk(clause: HtsClause) -> dict[str, object]:
    """Render an exact-fetched catalog clause into the same chunk shape as a dense hit."""
    metadata = clause.metadata()
    return {
        "hts_code": clause.hts_code,
        "title": metadata["title"],
        "restriction": metadata["restriction"],
        "duty_rate": metadata["duty_rate"],
        "content": clause.page_content(),
        "score": _EXACT_MATCH_SCORE,
        "match": "exact",
    }


def _exact_hits(query: str) -> list[dict[str, object]]:
    """Fetch the exact clause for each full HTS code named in the query (deduped, in order)."""
    chunks: list[dict[str, object]] = []
    seen: set[str] = set()
    for code in _HTS_CODE_PATTERN.findall(query):
        if code in seen:
            continue
        seen.add(code)
        clause = get_hts_clause(code)
        if clause is not None:
            chunks.append(_clause_to_chunk(clause))
    return chunks


def _merge(
    exact: list[dict[str, object]], dense: list[dict[str, object]], k: int
) -> list[dict[str, object]]:
    """Guarantee every exact hit (even past ``k``), then fill the remaining slots
    with dense hits, dropping any dense hit that duplicates an exact code."""
    exact_codes = {chunk["hts_code"] for chunk in exact}
    merged = list(exact)
    for chunk in dense:
        if len(merged) >= k:
            break
        if chunk["hts_code"] in exact_codes:
            continue
        merged.append(chunk)
    return merged


def run_retrieve_tariff_regulation(query: str, k: int = _DEFAULT_K) -> list[dict[str, object]]:
    """Pure core: merge exact-code fetches with dense search and append the call to the trace."""
    with record_tool_call("retrieve_tariff_regulation", {"query": query, "k": k}) as out:
        exact = _exact_hits(query)
        dense = [_to_chunk(doc, score) for doc, score in _similarity_search(query, k)]
        chunks = _merge(exact, dense, k)
        out["chunk_count"] = len(chunks)
        out["exact_hits"] = len(exact)
        out["hts_codes"] = [chunk["hts_code"] for chunk in chunks]
    return chunks


@tool
def retrieve_tariff_regulation(query: str) -> list[dict[str, object]]:
    """Retrieve up to 5 Harmonized Tariff Schedule (HTS) clauses relevant to the query from the
    shared regulation knowledge base. Returns clauses with their `hts_code` so your draft can cite
    them. The knowledge base is public HTS text and is not vendor-specific."""
    return run_retrieve_tariff_regulation(query)
