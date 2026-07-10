"""Unit tests for the pure config helper (no process-env mutation)."""

from src.config import resolve_cors_origins


def test_resolve_cors_origins_local_permits_vite() -> None:
    origins = resolve_cors_origins("local", "https://ignored.web.app")
    assert "http://localhost:5173" in origins
    assert "https://ignored.web.app" not in origins


def test_resolve_cors_origins_production_single_origin() -> None:
    assert resolve_cors_origins("production", "https://trade-agent-ff12a.web.app") == (
        "https://trade-agent-ff12a.web.app",
    )


def test_resolve_cors_origins_production_comma_separated_list() -> None:
    # The frontend is served from more than one host - each is a distinct browser origin
    # and needs its own explicit allow-list entry (the CORS spec forbids a wildcard when
    # ``allow_credentials=True``).
    assert resolve_cors_origins(
        "production",
        "https://trade-agent.samir.codes,https://trade-agent-ff12a.web.app",
    ) == (
        "https://trade-agent.samir.codes",
        "https://trade-agent-ff12a.web.app",
    )


def test_resolve_cors_origins_production_strips_whitespace_and_empties() -> None:
    # Tolerate the user pasting the env value with stray spaces or trailing commas.
    assert resolve_cors_origins("production", " https://a.example , ,https://b.example, ") == (
        "https://a.example",
        "https://b.example",
    )


def test_resolve_cors_origins_production_without_origins_is_empty() -> None:
    assert resolve_cors_origins("production", "") == ()
