"""Unit tests for the pure config helpers (no process-env mutation)."""

from src.config import parse_analyst_scopes, resolve_cors_origins


def test_parse_analyst_scopes_maps_emails_to_vendor_sets() -> None:
    result = parse_analyst_scopes(" Alice@Example.com = V-001,V-002 ; bob@test.io=v-003 ")
    assert result == {
        "alice@example.com": frozenset({"V-001", "V-002"}),  # email lowercased
        "bob@test.io": frozenset({"V-003"}),  # vendor id uppercased
    }


def test_parse_analyst_scopes_wildcard_grants_admin() -> None:
    assert parse_analyst_scopes("admin@x.com=*") == {"admin@x.com": frozenset({"*"})}


def test_parse_analyst_scopes_skips_malformed_and_empty() -> None:
    assert parse_analyst_scopes("") == {}
    assert parse_analyst_scopes("   ;  ; ") == {}
    # an entry without '=' or with no vendors is dropped, not added empty
    assert parse_analyst_scopes("no-equals;empty@x.com=") == {}


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
