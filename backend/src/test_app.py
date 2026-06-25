"""Integration tests for the API surface via FastAPI's TestClient.

The auth boundary is overridden (it is exercised in ``test_security.py``); the agent,
repository, and vendor-scope predicate are monkeypatched, so these tests cover routing,
request/response contracts, scope enforcement, and error mapping without any model,
Firestore, or credentials.

The ``auth_client`` fixture defaults the analyst to *admin* scope (the predicate allows
every vendor); scope-enforcement tests override the predicate to a narrow rule.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

import src.app as app_module
from src.agent import AgentResult, UnknownVendorError
from src.app import app
from src.models import (
    AgentTrace,
    GoodsCategory,
    ImportClassification,
    InquiryIntent,
    TraceDisposition,
    Vendor,
)
from src.security import verify_authorized_analyst

_VENDOR = Vendor(
    vendor_id="V-001",
    legal_name="Meridian Components LLC",
    country="Taiwan",
    customs_broker="Pacific Rim Customs Brokerage",
    categories=(GoodsCategory.ELECTRONICS,),
)
_VENDOR_2 = _VENDOR.model_copy(update={"vendor_id": "V-002", "legal_name": "Andes Textiles SA"})

_RESULT = AgentResult(
    trace_id="tr-abc",
    disposition=TraceDisposition.DRAFT,
    draft_response="Shipment S-1001 is held pending an import license.",
    classification=ImportClassification(
        intent=InquiryIntent.TARIFF_LOOKUP, confidence=0.9, reasoning="duty question"
    ),
    tool_call_count=4,
    tool_names=[
        "classify_import_restriction",
        "lookup_shipment_manifest",
        "retrieve_tariff_regulation",
        "draft_clearance_response",
    ],
    duration_ms=1234.5,
    model="gemini-2.5-flash",
)

_TRACE = AgentTrace(
    trace_id="tr-abc",
    timestamp="2026-06-25T00:00:00+00:00",
    vendor_id="V-001",
    user_inquiry="Why is S-1001 held?",
    disposition=TraceDisposition.DRAFT,
    model="gemini-2.5-flash",
)
_TRACE_2 = _TRACE.model_copy(update={"trace_id": "tr-def", "vendor_id": "V-002"})


@pytest.fixture
def auth_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """TestClient with the auth dependency overridden to an admin-scoped analyst.

    The vendor-scope predicate defaults to allow-all here so the happy-path tests focus on
    routing/contracts; scope-enforcement tests re-monkeypatch it to a narrow rule.
    """
    app.dependency_overrides[verify_authorized_analyst] = lambda: "analyst@example.com"
    monkeypatch.setattr(app_module, "analyst_can_access_vendor", lambda _email, _vendor_id: True)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


# --- Liveness + existing perimeter ---------------------------------------------
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


def test_me_with_authorized_identity_returns_email(auth_client: TestClient) -> None:
    resp = auth_client.get("/api/me")
    assert resp.status_code == 200
    assert resp.json() == {"email": "analyst@example.com", "authorized": True}


# --- POST /api/inquiry ----------------------------------------------------------
def test_inquiry_requires_auth() -> None:
    client = TestClient(app)
    resp = client.post("/api/inquiry", json={"vendor_id": "V-001", "inquiry": "hi"})
    assert resp.status_code in (401, 403)


def test_inquiry_runs_agent_and_returns_result(
    auth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, str]] = []

    def fake_run_agent(vendor_id: str, inquiry: str, model_id: str | None = None) -> AgentResult:
        calls.append((vendor_id, inquiry))
        return _RESULT

    monkeypatch.setattr(app_module, "run_agent", fake_run_agent)

    resp = auth_client.post(
        "/api/inquiry", json={"vendor_id": "V-001", "inquiry": "Why is S-1001 held?"}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["trace_id"] == "tr-abc"
    assert body["disposition"] == "draft"
    assert body["tool_call_count"] == 4
    assert body["classification"]["intent"] == "tariff_lookup"
    assert calls == [("V-001", "Why is S-1001 held?")]


def test_inquiry_out_of_scope_vendor_is_403(
    auth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The analyst is authorized for V-001 only; requesting V-002 must be refused.
    monkeypatch.setattr(app_module, "analyst_can_access_vendor", lambda _e, vid: vid == "V-001")

    def must_not_run(*_args: object, **_kwargs: object) -> AgentResult:
        raise AssertionError("run_agent must not be reached for an out-of-scope vendor")

    monkeypatch.setattr(app_module, "run_agent", must_not_run)

    resp = auth_client.post("/api/inquiry", json={"vendor_id": "V-002", "inquiry": "status?"})
    assert resp.status_code == 403


def test_inquiry_unknown_vendor_maps_to_404(
    auth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(vendor_id: str, inquiry: str, model_id: str | None = None) -> AgentResult:
        raise UnknownVendorError(vendor_id)

    monkeypatch.setattr(app_module, "run_agent", boom)

    resp = auth_client.post("/api/inquiry", json={"vendor_id": "V-404", "inquiry": "anything"})
    assert resp.status_code == 404
    assert "V-404" in resp.json()["detail"]


def test_inquiry_rejects_malformed_vendor_id(
    auth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def must_not_run(*_args: object, **_kwargs: object) -> AgentResult:
        raise AssertionError("run_agent must not be reached on a validation failure")

    monkeypatch.setattr(app_module, "run_agent", must_not_run)

    resp = auth_client.post("/api/inquiry", json={"vendor_id": "garbage", "inquiry": "hi"})
    assert resp.status_code == 422


def test_inquiry_rejects_empty_inquiry(auth_client: TestClient) -> None:
    resp = auth_client.post("/api/inquiry", json={"vendor_id": "V-001", "inquiry": ""})
    assert resp.status_code == 422


# --- GET /api/vendors -----------------------------------------------------------
def test_vendors_requires_auth() -> None:
    client = TestClient(app)
    assert client.get("/api/vendors").status_code in (401, 403)


def test_vendors_lists_for_the_dropdown(
    auth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module.repository, "list_vendors", lambda: [_VENDOR])

    resp = auth_client.get("/api/vendors")
    assert resp.status_code == 200
    body = resp.json()
    assert [v["vendor_id"] for v in body] == ["V-001"]
    assert body[0]["categories"] == ["electronics"]


def test_vendors_filtered_to_authorized_scope(
    auth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module.repository, "list_vendors", lambda: [_VENDOR, _VENDOR_2])
    monkeypatch.setattr(app_module, "analyst_can_access_vendor", lambda _e, vid: vid == "V-001")

    resp = auth_client.get("/api/vendors")
    assert resp.status_code == 200
    assert [v["vendor_id"] for v in resp.json()] == ["V-001"]  # V-002 filtered out


# --- GET /api/traces ------------------------------------------------------------
def test_traces_lists_recent(auth_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    seen_limit: list[int] = []

    def fake_recent(limit: int) -> list[AgentTrace]:
        seen_limit.append(limit)
        return [_TRACE]

    monkeypatch.setattr(app_module.repository, "list_recent_traces", fake_recent)

    resp = auth_client.get("/api/traces")
    assert resp.status_code == 200
    assert resp.json()[0]["trace_id"] == "tr-abc"
    assert seen_limit == [50]  # the recent-traces page size


def test_traces_filtered_to_authorized_scope(
    auth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        app_module.repository, "list_recent_traces", lambda _limit: [_TRACE, _TRACE_2]
    )
    monkeypatch.setattr(app_module, "analyst_can_access_vendor", lambda _e, vid: vid == "V-001")

    resp = auth_client.get("/api/traces")
    assert resp.status_code == 200
    assert [t["trace_id"] for t in resp.json()] == ["tr-abc"]  # V-002 trace filtered out


# --- POST /api/traces/{trace_id}/disposition ------------------------------------
def test_disposition_records_human_decision(
    auth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    updates: list[tuple[str, TraceDisposition]] = []

    monkeypatch.setattr(app_module.repository, "get_trace", lambda _tid: _TRACE)
    monkeypatch.setattr(
        app_module.repository,
        "update_trace_disposition",
        lambda tid, disp: updates.append((tid, disp)),
    )

    resp = auth_client.post("/api/traces/tr-abc/disposition", json={"disposition": "approved"})
    assert resp.status_code == 200
    assert resp.json() == {"trace_id": "tr-abc", "disposition": "approved"}
    assert updates == [("tr-abc", TraceDisposition.APPROVED)]


def test_disposition_out_of_scope_is_403(
    auth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # tr-def belongs to V-002; the analyst is scoped to V-001 only.
    monkeypatch.setattr(app_module.repository, "get_trace", lambda _tid: _TRACE_2)
    monkeypatch.setattr(app_module, "analyst_can_access_vendor", lambda _e, vid: vid == "V-001")

    def must_not_update(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("update must not be reached for an out-of-scope trace")

    monkeypatch.setattr(app_module.repository, "update_trace_disposition", must_not_update)

    resp = auth_client.post("/api/traces/tr-def/disposition", json={"disposition": "approved"})
    assert resp.status_code == 403


def test_disposition_rejects_non_review_value(auth_client: TestClient) -> None:
    # Only approve/reject are caller-settable; "draft" is agent-written and refused.
    resp = auth_client.post("/api/traces/tr-abc/disposition", json={"disposition": "draft"})
    assert resp.status_code == 422


def test_disposition_unknown_trace_maps_to_404(
    auth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module.repository, "get_trace", lambda _tid: None)

    resp = auth_client.post("/api/traces/tr-zzz/disposition", json={"disposition": "rejected"})
    assert resp.status_code == 404
