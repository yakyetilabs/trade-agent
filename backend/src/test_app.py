"""Integration tests for the API surface via FastAPI's TestClient."""

from fastapi.testclient import TestClient

from src.app import app
from src.security import verify_authorized_analyst


def test_health_is_open_and_ok() -> None:
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_me_without_token_is_blocked() -> None:
    client = TestClient(app)
    resp = client.get("/api/me")
    # HTTPBearer(auto_error=True) returns 403 when the Authorization header is absent.
    assert resp.status_code in (401, 403)


def test_me_with_authorized_identity_returns_email() -> None:
    app.dependency_overrides[verify_authorized_analyst] = lambda: "analyst@example.com"
    try:
        client = TestClient(app)
        resp = client.get("/api/me")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json() == {"email": "analyst@example.com", "authorized": True}
