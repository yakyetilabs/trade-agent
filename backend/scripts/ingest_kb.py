"""Embed the synthetic HTS clauses and upsert them into the Pinecone KB.

The knowledge base is shared, public-style HTS reference text — it is deliberately
*not* vendor-partitioned. Each clause is embedded with Vertex AI
``gemini-embedding-001`` at 768 dimensions (via the shared ``VertexEmbeddings``
adapter, which pins ``output_dimensionality`` explicitly) and upserted into the
Pinecone index keyed by HTS code, so a re-ingest overwrites rather than
duplicates. ``retrieve_tariff_regulation`` (Phase 3) queries this same store.

Usage (from ``backend/``):

    uv run python -m scripts.ingest_kb            # embed + upsert to Pinecone
    uv run python -m scripts.ingest_kb --dry-run  # print docs/ids, no network

The index must already exist at 768-dim / cosine / AWS us-east-1 (see
docs/GCP_SETUP.md §7). Live ingest needs ``PINECONE_API_KEY`` and Google creds.
"""

import argparse

from langchain_core.documents import Document

from src.config import (
    PINECONE_API_KEY,
    PINECONE_INDEX,
    VERTEX_EMBEDDING_DIM,
    VERTEX_EMBEDDING_MODEL,
)
from src.data.generators import build_hts_clauses


def _build_documents() -> tuple[list[Document], list[str]]:
    """Render every HTS clause into a (Document, id) pair keyed by HTS code."""
    documents: list[Document] = []
    ids: list[str] = []
    for clause in build_hts_clauses():
        documents.append(
            Document(
                id=clause.hts_code,
                page_content=clause.page_content(),
                metadata=clause.metadata(),
            )
        )
        ids.append(clause.hts_code)
    return documents, ids


def _ingest(documents: list[Document], ids: list[str]) -> None:
    """Embed at 768-dim and upsert into the Pinecone index (overwrite by id)."""
    # Imported lazily so --dry-run needs no credentials or heavy SDK import.
    from langchain_pinecone import PineconeVectorStore

    from src.embeddings import VertexEmbeddings

    if not PINECONE_API_KEY:
        raise SystemExit("PINECONE_API_KEY is not set - populate backend/.env first.")

    embeddings = VertexEmbeddings()

    # Fail fast if the embedder's output width doesn't match the fixed index
    # dimension — Pinecone would otherwise reject the upsert with an opaque error.
    probe_dim = len(embeddings.embed_query(documents[0].page_content))
    if probe_dim != VERTEX_EMBEDDING_DIM:
        raise SystemExit(
            f"Embedding width {probe_dim} != expected {VERTEX_EMBEDDING_DIM}; "
            f"the Pinecone index '{PINECONE_INDEX}' is fixed at {VERTEX_EMBEDDING_DIM}-dim."
        )
    print(f"Embedding width confirmed: {probe_dim} dimensions.")

    store = PineconeVectorStore(
        index_name=PINECONE_INDEX,
        pinecone_api_key=PINECONE_API_KEY,
        embedding=embeddings,
    )
    store.add_documents(documents, ids=ids)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest the HTS KB into Pinecone.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the documents and ids without embedding or upserting.",
    )
    args = parser.parse_args()

    documents, ids = _build_documents()

    if args.dry_run:
        print(f"DRY RUN — {len(documents)} clause(s), no network calls:")
        for doc in documents:
            print(f"  [dry-run] {PINECONE_INDEX}/{doc.id} ({len(doc.page_content)} chars)")
        return

    print(
        f"Ingesting {len(documents)} HTS clause(s) into Pinecone index "
        f"'{PINECONE_INDEX}' via {VERTEX_EMBEDDING_MODEL} @ {VERTEX_EMBEDDING_DIM}-dim."
    )
    _ingest(documents, ids)
    print(f"Done: upserted {len(ids)} clause(s) into '{PINECONE_INDEX}'.")


if __name__ == "__main__":
    main()
