"""Tool 3: retrieve_tariff_regulation (semantic KB retrieval).

Queries the shared Harmonized Tariff Schedule knowledge base in Pinecone and
returns up to ``k`` clauses, each carrying its ``hts_code`` so the draft can cite
it. The KB is public HTS text and is deliberately *not* vendor-partitioned, so —
unlike the reference's plan-scoped policy retrieval — there is no vendor filter
and no per-call vendor read.

The raw vector-store result is normalized into a stable chunk dict; the Pinecone
SDK shape never leaks upward.
"""

from functools import lru_cache

from langchain_core.documents import Document
from langchain_core.tools import tool
from langchain_pinecone import PineconeVectorStore

from src.config import PINECONE_API_KEY, PINECONE_INDEX
from src.embeddings import VertexEmbeddings
from src.tracing.trace_context import record_tool_call

_DEFAULT_K = 5


@lru_cache(maxsize=1)
def _vector_store() -> PineconeVectorStore:
    """Construct the Pinecone-backed vector store once (Vertex embeds, Pinecone stores)."""
    return PineconeVectorStore(
        index_name=PINECONE_INDEX,
        pinecone_api_key=PINECONE_API_KEY,
        embedding=VertexEmbeddings(),
    )


def _similarity_search(query: str, k: int) -> list[tuple[Document, float]]:
    """Run the vector search — the test seam for this tool."""
    return _vector_store().similarity_search_with_score(query, k=k)


def _to_chunk(document: Document, score: float) -> dict[str, object]:
    metadata: dict[str, object] = dict(document.metadata or {})
    return {
        "hts_code": metadata.get("hts_code"),
        "title": metadata.get("title"),
        "restriction": metadata.get("restriction"),
        "duty_rate": metadata.get("duty_rate"),
        "content": document.page_content,
        "score": score,
    }


def run_retrieve_tariff_regulation(query: str, k: int = _DEFAULT_K) -> list[dict[str, object]]:
    """Pure core: semantic-search the HTS KB and append the call to the trace."""
    with record_tool_call("retrieve_tariff_regulation", {"query": query, "k": k}) as out:
        chunks = [_to_chunk(doc, score) for doc, score in _similarity_search(query, k)]
        out["chunk_count"] = len(chunks)
        out["hts_codes"] = [chunk["hts_code"] for chunk in chunks]
    return chunks


@tool
def retrieve_tariff_regulation(query: str) -> list[dict[str, object]]:
    """Retrieve up to 5 Harmonized Tariff Schedule (HTS) clauses relevant to the query from the
    shared regulation knowledge base. Returns clauses with their `hts_code` so your draft can cite
    them. The knowledge base is public HTS text and is not vendor-specific."""
    return run_retrieve_tariff_regulation(query)
