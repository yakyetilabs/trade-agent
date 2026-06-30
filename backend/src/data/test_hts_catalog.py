"""Unit tests for the shared in-process HTS catalog index."""

from src.data.hts_catalog import get_hts_clause


def test_known_code_resolves_to_its_clause() -> None:
    clause = get_hts_clause("8517.13.0000")
    assert clause is not None
    assert clause.title == "Smartphones"


def test_unknown_code_returns_none() -> None:
    assert get_hts_clause("0000.00.0000") is None
