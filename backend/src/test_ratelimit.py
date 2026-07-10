"""Hermetic unit tests for the per-IP token-bucket rate limiter (no clock, no network).

Time is a fake monotonic clock injected into the limiter, so refill behavior is exact
and instant. Endpoint-level 429 wiring is covered in ``test_app.py``.
"""

import pytest

from src.ratelimit import RateLimiter, resolve_client_ip


class FakeClock:
    """A controllable monotonic clock: ``advance`` moves time forward in seconds."""

    def __init__(self) -> None:
        self.now: float = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_limiter(
    *,
    rpm: int = 5,
    tpm: int = 1_000,
    window: float = 60.0,
    max_tracked_ips: int = 10_000,
) -> tuple[RateLimiter, FakeClock]:
    clock = FakeClock()
    limiter = RateLimiter(
        requests_per_window=rpm,
        tokens_per_window=tpm,
        window_seconds=window,
        max_tracked_ips=max_tracked_ips,
        clock=clock,
    )
    return limiter, clock


# --- Request budget (RPM) ---------------------------------------------------------
def test_allows_bursts_up_to_the_full_window_quota() -> None:
    limiter, _ = make_limiter(rpm=3)
    verdicts = [limiter.check_and_reserve("1.2.3.4").allowed for _ in range(4)]
    # A fresh bucket is full: the whole window's quota may be spent at once, then deny.
    assert verdicts == [True, True, True, False]


def test_denial_carries_retry_after_and_exhausted_headers() -> None:
    limiter, _ = make_limiter(rpm=1)
    assert limiter.check_and_reserve("1.2.3.4").allowed
    denied = limiter.check_and_reserve("1.2.3.4")
    assert not denied.allowed
    assert denied.retry_after_seconds >= 1
    assert denied.headers["Retry-After"] == str(denied.retry_after_seconds)
    assert denied.headers["X-RateLimit-Remaining-Requests"] == "0"


def test_request_budget_refills_steadily_with_time() -> None:
    limiter, clock = make_limiter(rpm=6, window=60.0)  # refill: one request per 10s
    for _ in range(6):
        assert limiter.check_and_reserve("1.2.3.4").allowed
    assert not limiter.check_and_reserve("1.2.3.4").allowed
    clock.advance(10.0)  # exactly one request re-earned
    assert limiter.check_and_reserve("1.2.3.4").allowed
    assert not limiter.check_and_reserve("1.2.3.4").allowed


def test_ips_have_independent_budgets() -> None:
    limiter, _ = make_limiter(rpm=1)
    assert limiter.check_and_reserve("1.1.1.1").allowed
    assert not limiter.check_and_reserve("1.1.1.1").allowed
    assert limiter.check_and_reserve("2.2.2.2").allowed


# --- Token budget (TPM) -----------------------------------------------------------
def test_token_debit_reduces_the_budget_headers() -> None:
    limiter, _ = make_limiter(tpm=1_000)
    limiter.debit_tokens("1.2.3.4", 400)
    decision = limiter.check_and_reserve("1.2.3.4")
    assert decision.allowed
    assert decision.headers["X-RateLimit-Remaining-Tokens"] == "600"


def test_exhausted_token_budget_denies_even_with_requests_left() -> None:
    limiter, _ = make_limiter(rpm=10, tpm=1_000)
    limiter.debit_tokens("1.2.3.4", 1_000)
    denied = limiter.check_and_reserve("1.2.3.4")
    assert not denied.allowed
    assert denied.headers["X-RateLimit-Remaining-Tokens"] == "0"
    assert int(denied.headers["X-RateLimit-Remaining-Requests"]) > 0


def test_overshoot_blocks_proportionally_longer_then_refills() -> None:
    # Tokens are debited after the run, so one run may overshoot; the deficit must
    # extend the wait proportionally, and refill must eventually re-admit the IP.
    limiter, clock = make_limiter(rpm=10, tpm=600, window=60.0)  # refill: 10 tokens/s
    limiter.debit_tokens("1.2.3.4", 1_200)  # 600 over budget -> 60s to reach zero
    denied = limiter.check_and_reserve("1.2.3.4")
    assert not denied.allowed
    assert denied.retry_after_seconds > 60  # deeper than a plain-exhaustion wait
    clock.advance(30.0)
    assert not limiter.check_and_reserve("1.2.3.4").allowed
    clock.advance(45.0)  # 75s total: deficit cleared with margin
    assert limiter.check_and_reserve("1.2.3.4").allowed


def test_zero_or_negative_debit_is_a_no_op() -> None:
    limiter, _ = make_limiter(tpm=1_000)
    limiter.debit_tokens("1.2.3.4", 0)
    limiter.debit_tokens("1.2.3.4", -5)
    assert limiter.check_and_reserve("1.2.3.4").headers["X-RateLimit-Remaining-Tokens"] == "1000"


# --- Headers ----------------------------------------------------------------------
def test_allowed_decision_headers_cover_both_budgets() -> None:
    limiter, _ = make_limiter(rpm=5, tpm=1_000)
    headers = limiter.check_and_reserve("1.2.3.4").headers
    assert headers["X-RateLimit-Limit-Requests"] == "5"
    assert headers["X-RateLimit-Remaining-Requests"] == "4"
    assert int(headers["X-RateLimit-Reset-Requests"]) >= 1  # one request was reserved
    assert headers["X-RateLimit-Limit-Tokens"] == "1000"
    assert headers["X-RateLimit-Remaining-Tokens"] == "1000"
    assert headers["X-RateLimit-Reset-Tokens"] == "0"  # untouched budget: nothing to reset
    assert "Retry-After" not in headers


# --- Bounded memory ---------------------------------------------------------------
def test_stale_buckets_are_evicted_when_the_store_is_full() -> None:
    limiter, clock = make_limiter(window=60.0, max_tracked_ips=3)
    for ip in ("a", "b", "c"):
        limiter.check_and_reserve(ip)
    clock.advance(121.0)  # past two windows: all three are stale (fully re-earned)
    limiter.check_and_reserve("d")
    assert limiter.tracked_ip_count == 1  # a/b/c pruned, d inserted


def test_saturated_store_evicts_the_least_recently_seen_ip() -> None:
    limiter, clock = make_limiter(rpm=1, max_tracked_ips=2)
    assert limiter.check_and_reserve("a").allowed
    clock.advance(1.0)
    assert limiter.check_and_reserve("b").allowed
    clock.advance(1.0)
    limiter.check_and_reserve("c")  # store full, nothing stale -> "a" (oldest) evicted
    assert limiter.tracked_ip_count == 2
    # "a" re-enters with a fresh budget: the documented forgiveness that buys the bound.
    assert limiter.check_and_reserve("a").allowed


# --- Construction guardrails ------------------------------------------------------
def test_rejects_non_positive_quotas() -> None:
    with pytest.raises(ValueError):
        RateLimiter(requests_per_window=0, tokens_per_window=1, window_seconds=60.0)
    with pytest.raises(ValueError):
        RateLimiter(requests_per_window=1, tokens_per_window=1, window_seconds=0.0)


# --- Client-IP resolution ---------------------------------------------------------
def test_client_ip_is_the_rightmost_xff_entry() -> None:
    # The rightmost entry is appended by Google's front end for the actual peer;
    # leading entries are caller-supplied and spoofable.
    assert resolve_client_ip("203.0.113.7, 198.51.100.9", "10.0.0.1") == "198.51.100.9"


def test_client_ip_tolerates_whitespace_and_empty_entries() -> None:
    assert resolve_client_ip(" 203.0.113.7 , , 198.51.100.9 , ", None) == "198.51.100.9"


def test_client_ip_falls_back_to_the_socket_peer() -> None:
    assert resolve_client_ip(None, "127.0.0.1") == "127.0.0.1"
    assert resolve_client_ip("", "127.0.0.1") == "127.0.0.1"


def test_client_ip_last_resort_is_unknown() -> None:
    assert resolve_client_ip(None, None) == "unknown"
