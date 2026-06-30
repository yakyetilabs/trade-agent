"""Unit tests for retrieve_tariff_regulation.

The vector-search seam (``_similarity_search``) is monkeypatched, so no Vertex
embedding or Pinecone call happens. The exact-fetch path needs no mock: it reads
the deterministic in-process HTS catalog directly.
"""

import pytest
from langchain_core.documents import Document

import src.tools.retrieve_tariff_regulation as retrieve_mod
from src.tracing.trace_context import trace_context


def _dense_doc(hts_code: str, title: str, restriction: str, duty_rate: str) -> Document:
    """Build a Pinecone-shaped dense hit document for the search stub."""
    return Document(
        page_content=f"HTS {hts_code} - {title}.",
        metadata={
            "hts_code": hts_code,
            "title": title,
            "restriction": restriction,
            "duty_rate": duty_rate,
        },
    )


def test_run_retrieve_normalizes_dense_chunks_and_records_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _dense_doc("8517.13.0000", "Smartphones", "unrestricted", "Free")
    monkeypatch.setattr(retrieve_mod, "_similarity_search", lambda _q, _k: [(document, 0.91)])

    with trace_context("tr-1", "V-001") as ctx:
        chunks = retrieve_mod.run_retrieve_tariff_regulation("smartphone duty rate")

    assert len(chunks) == 1
    assert chunks[0]["hts_code"] == "8517.13.0000"
    assert chunks[0]["score"] == 0.91
    assert chunks[0]["match"] == "semantic"
    assert "Smartphones" in str(chunks[0]["content"])
    # No HTS code in the query -> pure dense, zero exact hits (the prior behavior).
    assert ctx.tool_calls[0].output["chunk_count"] == 1
    assert ctx.tool_calls[0].output["exact_hits"] == 0
    assert ctx.tool_calls[0].output["hts_codes"] == ["8517.13.0000"]


def test_exact_code_in_query_is_guaranteed_even_when_dense_omits_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Dense search returns an unrelated clause and never surfaces 8542.31.0001.
    other = _dense_doc("8471.30.0100", "Portable computers", "unrestricted", "Free")
    monkeypatch.setattr(retrieve_mod, "_similarity_search", lambda _q, _k: [(other, 0.42)])

    with trace_context("tr-2", "V-001") as ctx:
        chunks = retrieve_mod.run_retrieve_tariff_regulation(
            "Do I need a license to import 8542.31.0001?"
        )

    exact = next(c for c in chunks if c["hts_code"] == "8542.31.0001")
    assert exact["match"] == "exact"
    assert exact["score"] == 1.0  # sentinel, not a cosine similarity
    assert exact["restriction"] == "license_required"  # straight from the catalog
    assert chunks[0]["hts_code"] == "8542.31.0001"  # exact hits lead the result
    assert ctx.tool_calls[0].output["exact_hits"] == 1


def test_dense_duplicate_of_exact_code_is_deduped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Dense search redundantly returns the code the query names, plus a distinct one.
    duplicate = _dense_doc("8517.13.0000", "Smartphones", "unrestricted", "Free")
    distinct = _dense_doc("8471.30.0100", "Portable computers", "unrestricted", "Free")
    monkeypatch.setattr(
        retrieve_mod, "_similarity_search", lambda _q, _k: [(duplicate, 0.88), (distinct, 0.71)]
    )

    with trace_context("tr-3", "V-001") as ctx:
        chunks = retrieve_mod.run_retrieve_tariff_regulation("clarify 8517.13.0000 please")

    codes = [chunk["hts_code"] for chunk in chunks]
    assert codes.count("8517.13.0000") == 1  # not duplicated across the exact + dense merge
    smartphone = next(c for c in chunks if c["hts_code"] == "8517.13.0000")
    assert smartphone["match"] == "exact"  # the deterministic clause supersedes the fuzzy hit
    assert "8471.30.0100" in codes  # the non-duplicate dense hit still survives
    assert ctx.tool_calls[0].output["exact_hits"] == 1
    assert ctx.tool_calls[0].output["chunk_count"] == 2


def test_retrieve_tool_exposes_only_query_to_the_model() -> None:
    assert set(retrieve_mod.retrieve_tariff_regulation.args.keys()) == {"query"}
