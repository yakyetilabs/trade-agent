"""Unit tests for retrieve_tariff_regulation.

The vector-search seam (``_similarity_search``) is monkeypatched, so no Vertex
embedding or Pinecone call happens.
"""

import pytest
from langchain_core.documents import Document

import src.tools.retrieve_tariff_regulation as retrieve_mod
from src.tracing.trace_context import trace_context


def test_run_retrieve_normalizes_chunks_and_records_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = Document(
        page_content="HTS 8517.13.0000 — Smartphones. Admitted free of duty.",
        metadata={
            "hts_code": "8517.13.0000",
            "title": "Smartphones",
            "restriction": "unrestricted",
            "duty_rate": "Free",
        },
    )
    monkeypatch.setattr(
        retrieve_mod, "_similarity_search", lambda _q, _k: [(document, 0.91)]
    )

    with trace_context("tr-1", "V-001") as ctx:
        chunks = retrieve_mod.run_retrieve_tariff_regulation("smartphone duty rate")

    assert len(chunks) == 1
    assert chunks[0]["hts_code"] == "8517.13.0000"
    assert chunks[0]["score"] == 0.91
    assert "Smartphones" in str(chunks[0]["content"])
    # Trace summary cites the retrieved codes.
    assert ctx.tool_calls[0].output["chunk_count"] == 1
    assert ctx.tool_calls[0].output["hts_codes"] == ["8517.13.0000"]


def test_retrieve_tool_exposes_only_query_to_the_model() -> None:
    assert set(retrieve_mod.retrieve_tariff_regulation.args.keys()) == {"query"}
