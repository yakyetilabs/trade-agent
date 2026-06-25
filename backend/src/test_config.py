"""Unit tests for the pure config helpers (no process-env mutation)."""

from src.config import parse_allowlist, resolve_cors_origins


def test_parse_allowlist_lowercases_strips_and_dedupes() -> None:
    result = parse_allowlist(" Alice@Example.com , bob@test.io , ALICE@example.com ,")
    assert result == frozenset({"alice@example.com", "bob@test.io"})


def test_parse_allowlist_empty_string_yields_empty_set() -> None:
    assert parse_allowlist("") == frozenset()
    assert parse_allowlist("   ,  , ") == frozenset()


def test_resolve_cors_origins_local_permits_vite() -> None:
    origins = resolve_cors_origins("local", "https://ignored.web.app")
    assert "http://localhost:5173" in origins
    assert "https://ignored.web.app" not in origins


def test_resolve_cors_origins_production_locks_to_prod_origin() -> None:
    assert resolve_cors_origins("production", "https://trade-agent-a5208.web.app") == (
        "https://trade-agent-a5208.web.app",
    )


def test_resolve_cors_origins_production_without_origin_is_empty() -> None:
    assert resolve_cors_origins("production", "") == ()
