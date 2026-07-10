"""Integration tests for the API surface via FastAPI's TestClient.

The API is a public demo (no auth); the agent and repository are monkeypatched, so
these tests cover routing, request/response contracts, and error mapping without any
model, Firestore, or credentials.
"""

from collections.abc import AsyncIterator

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
from src.ratelimit import RateLimiter
from src.streaming import DoneEvent, RunStartedEvent, StreamEvent

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


def _install_limiter(
    monkeypatch: pytest.MonkeyPatch,
    *,
    requests_per_window: int,
    tokens_per_window: int,
    window_seconds: float = 60.0,
) -> RateLimiter:
    """Swap the app's per-IP limiter for a scratch instance with the given quotas."""
    limiter = RateLimiter(
        requests_per_window=requests_per_window,
        tokens_per_window=tokens_per_window,
        window_seconds=window_seconds,
    )
    monkeypatch.setattr(app_module, "rate_limiter", limiter)
    return limiter


@pytest.fixture(autouse=True)
def generous_rate_limiter(monkeypatch: pytest.MonkeyPatch) -> RateLimiter:
    """Every test gets a fresh, effectively-unlimited limiter so budgets never leak
    across tests; the rate-limit tests below install tighter ones on top."""
    return _install_limiter(
        monkeypatch,
        requests_per_window=100_000,
        tokens_per_window=1_000_000_000,
        window_seconds=60.0,
    )


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


# --- Liveness --------------------------------------------------------------------
def test_health_is_open_and_ok(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# --- POST /api/inquiry ----------------------------------------------------------
def test_inquiry_runs_agent_and_returns_result(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, str]] = []

    def fake_run_agent(vendor_id: str, inquiry: str, model_id: str | None = None) -> AgentResult:
        calls.append((vendor_id, inquiry))
        return _RESULT

    monkeypatch.setattr(app_module, "run_agent", fake_run_agent)

    resp = client.post(
        "/api/inquiry", json={"vendor_id": "V-001", "inquiry": "Why is S-1001 held?"}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["trace_id"] == "tr-abc"
    assert body["disposition"] == "draft"
    assert body["tool_call_count"] == 4
    assert body["classification"]["intent"] == "tariff_lookup"
    assert calls == [("V-001", "Why is S-1001 held?")]


def test_inquiry_needs_no_auth_header(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # Public demo: a bare request with no Authorization header reaches the agent.
    monkeypatch.setattr(app_module, "run_agent", lambda *_a, **_k: _RESULT)

    resp = client.post("/api/inquiry", json={"vendor_id": "V-002", "inquiry": "status?"})
    assert resp.status_code == 200
    assert resp.json()["trace_id"] == "tr-abc"


def test_inquiry_unknown_vendor_maps_to_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(vendor_id: str, inquiry: str, model_id: str | None = None) -> AgentResult:
        raise UnknownVendorError(vendor_id)

    monkeypatch.setattr(app_module, "run_agent", boom)

    resp = client.post("/api/inquiry", json={"vendor_id": "V-404", "inquiry": "anything"})
    assert resp.status_code == 404
    assert "V-404" in resp.json()["detail"]


def test_inquiry_rejects_malformed_vendor_id(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def must_not_run(*_args: object, **_kwargs: object) -> AgentResult:
        raise AssertionError("run_agent must not be reached on a validation failure")

    monkeypatch.setattr(app_module, "run_agent", must_not_run)

    resp = client.post("/api/inquiry", json={"vendor_id": "garbage", "inquiry": "hi"})
    assert resp.status_code == 422


def test_inquiry_rejects_empty_inquiry(client: TestClient) -> None:
    resp = client.post("/api/inquiry", json={"vendor_id": "V-001", "inquiry": ""})
    assert resp.status_code == 422


# --- POST /api/inquiry/stream ---------------------------------------------------
def test_inquiry_stream_emits_sse_events(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_stream(
        vendor_id: str, inquiry: str, model_id: str | None = None
    ) -> AsyncIterator[StreamEvent]:
        yield RunStartedEvent(trace_id="tr-abc", vendor_id=vendor_id, model="gemini-2.5-flash")
        yield DoneEvent(result=_RESULT)

    monkeypatch.setattr(app_module, "stream_agent_run", fake_stream)

    resp = client.post(
        "/api/inquiry/stream", json={"vendor_id": "V-001", "inquiry": "Why is S-1001 held?"}
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.headers["cache-control"] == "no-store"
    body = resp.text
    assert "event: run_started" in body
    assert "event: done" in body
    assert "tr-abc" in body  # the AgentResult rode through in the done event's data payload


def test_inquiry_stream_rejects_malformed_vendor_id(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def must_not_stream(*_args: object, **_kwargs: object) -> AsyncIterator[StreamEvent]:
        raise AssertionError("stream_agent_run must not run on a validation failure")
        yield  # pragma: no cover - unreachable; only marks this an async generator

    monkeypatch.setattr(app_module, "stream_agent_run", must_not_stream)

    resp = client.post("/api/inquiry/stream", json={"vendor_id": "garbage", "inquiry": "hi"})
    assert resp.status_code == 422


# --- GET /api/vendors -----------------------------------------------------------
def test_vendors_lists_all_for_the_dropdown(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module.repository, "list_vendors", lambda: [_VENDOR, _VENDOR_2])

    resp = client.get("/api/vendors")
    assert resp.status_code == 200
    body = resp.json()
    # Public demo: the full vendor list, unfiltered.
    assert [v["vendor_id"] for v in body] == ["V-001", "V-002"]
    assert body[0]["categories"] == ["electronics"]


# --- GET /api/traces ------------------------------------------------------------
def test_traces_lists_recent_unfiltered(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen_limit: list[int] = []

    def fake_recent(limit: int) -> list[AgentTrace]:
        seen_limit.append(limit)
        return [_TRACE, _TRACE_2]

    monkeypatch.setattr(app_module.repository, "list_recent_traces", fake_recent)

    resp = client.get("/api/traces")
    assert resp.status_code == 200
    assert [t["trace_id"] for t in resp.json()] == ["tr-abc", "tr-def"]
    assert seen_limit == [50]  # the recent-traces page size


# --- POST /api/traces/{trace_id}/disposition ------------------------------------
def test_disposition_records_human_decision(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    updates: list[tuple[str, TraceDisposition]] = []

    monkeypatch.setattr(app_module.repository, "get_trace", lambda _tid: _TRACE)
    monkeypatch.setattr(
        app_module.repository,
        "update_trace_disposition",
        lambda tid, disp: updates.append((tid, disp)),
    )

    resp = client.post("/api/traces/tr-abc/disposition", json={"disposition": "approved"})
    assert resp.status_code == 200
    assert resp.json() == {"trace_id": "tr-abc", "disposition": "approved"}
    assert updates == [("tr-abc", TraceDisposition.APPROVED)]


def test_disposition_rejects_non_review_value(client: TestClient) -> None:
    # Only approve/reject are caller-settable; "draft" is agent-written and refused.
    resp = client.post("/api/traces/tr-abc/disposition", json={"disposition": "draft"})
    assert resp.status_code == 422


def test_disposition_unknown_trace_maps_to_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module.repository, "get_trace", lambda _tid: None)

    resp = client.post("/api/traces/tr-zzz/disposition", json={"disposition": "rejected"})
    assert resp.status_code == 404


# --- Per-IP rate limiting (src/ratelimit.py wiring) -------------------------------
def test_api_returns_429_when_the_request_budget_is_spent(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_limiter(monkeypatch, requests_per_window=1, tokens_per_window=1_000_000)
    monkeypatch.setattr(app_module.repository, "list_vendors", lambda: [_VENDOR])

    assert client.get("/api/vendors").status_code == 200
    resp = client.get("/api/vendors")
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers
    assert resp.headers["X-RateLimit-Remaining-Requests"] == "0"
    assert "Rate limit exceeded" in resp.json()["detail"]


def test_success_responses_carry_rate_limit_headers(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_limiter(monkeypatch, requests_per_window=50, tokens_per_window=1_000_000)
    monkeypatch.setattr(app_module.repository, "list_vendors", lambda: [_VENDOR])

    resp = client.get("/api/vendors")
    assert resp.status_code == 200
    assert resp.headers["X-RateLimit-Limit-Requests"] == "50"
    assert resp.headers["X-RateLimit-Remaining-Requests"] == "49"
    assert resp.headers["X-RateLimit-Limit-Tokens"] == "1000000"


def test_health_is_never_rate_limited(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_limiter(monkeypatch, requests_per_window=1, tokens_per_window=1_000_000)
    monkeypatch.setattr(app_module.repository, "list_vendors", lambda: [_VENDOR])

    assert client.get("/api/vendors").status_code == 200  # budget now spent
    assert client.get("/api/vendors").status_code == 429
    assert client.get("/health").status_code == 200  # liveness stays outside the limiter


def test_inquiry_debits_actual_tokens_against_the_tpm_budget(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 12k actual tokens overshoot the 10k budget: the first run is admitted (tokens are
    # unknowable up front), the second is refused until refill.
    _install_limiter(monkeypatch, requests_per_window=100, tokens_per_window=10_000)
    heavy = _RESULT.model_copy(update={"total_tokens": 12_000})
    monkeypatch.setattr(app_module, "run_agent", lambda *_a, **_k: heavy)

    body = {"vendor_id": "V-001", "inquiry": "Why is S-1001 held?"}
    assert client.post("/api/inquiry", json=body).status_code == 200
    resp = client.post("/api/inquiry", json=body)
    assert resp.status_code == 429
    assert resp.headers["X-RateLimit-Remaining-Tokens"] == "0"
    assert int(resp.headers["X-RateLimit-Remaining-Requests"]) > 0  # RPM was not the cause


def test_stream_debits_tokens_and_carries_rate_limit_headers(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_limiter(monkeypatch, requests_per_window=100, tokens_per_window=10_000)
    heavy = _RESULT.model_copy(update={"total_tokens": 12_000})

    async def fake_stream(
        vendor_id: str, inquiry: str, model_id: str | None = None
    ) -> AsyncIterator[StreamEvent]:
        yield RunStartedEvent(trace_id="tr-abc", vendor_id=vendor_id, model="gemini-2.5-flash")
        yield DoneEvent(result=heavy)

    monkeypatch.setattr(app_module, "stream_agent_run", fake_stream)

    body = {"vendor_id": "V-001", "inquiry": "Why is S-1001 held?"}
    first = client.post("/api/inquiry/stream", json=body)
    assert first.status_code == 200
    # The streaming route attaches the headers itself (FastAPI merges dependency-set
    # headers only onto serialized responses, not a directly returned Response).
    assert first.headers["X-RateLimit-Limit-Tokens"] == "10000"
    # The done event's total_tokens were debited when the stream closed.
    assert client.post("/api/inquiry/stream", json=body).status_code == 429


def test_rate_limit_keys_on_the_rightmost_forwarded_ip(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Same spoofable leading entry, different Google-appended peer: distinct budgets.
    _install_limiter(monkeypatch, requests_per_window=1, tokens_per_window=1_000_000)
    monkeypatch.setattr(app_module.repository, "list_vendors", lambda: [_VENDOR])

    peer_a = {"X-Forwarded-For": "203.0.113.7, 198.51.100.9"}
    peer_b = {"X-Forwarded-For": "203.0.113.7, 192.0.2.33"}
    assert client.get("/api/vendors", headers=peer_a).status_code == 200
    assert client.get("/api/vendors", headers=peer_a).status_code == 429
    assert client.get("/api/vendors", headers=peer_b).status_code == 200
