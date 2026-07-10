"""In-app per-IP rate limiting - the request-admission half of the public-demo spend posture.

One token-bucket core carries two per-IP budgets (docs/DESIGN_DECISIONS.md §11):

- Requests: every ``/api/*`` hit reserves 1 request up front (deny = HTTP 429).
- Model tokens: the two inquiry endpoints debit each run's actual ``total_tokens`` after
  the run finishes. A run's cost is unknowable at admission, so the pre-check only asks
  "is this IP's token budget already exhausted?" - one request may overshoot the budget,
  and that IP then waits for refill. Debit-after overshoot is standard token-limit
  behavior (the Anthropic/OpenAI shape), not a gap.

The store is in-memory and per-instance-approximate BY DESIGN: state resets on cold start
and is not shared across instances - an acceptable error bound under the low Cloud Run
instance ceiling - and it keeps the request-admission path free of database reads, so
hostile traffic cannot drain the Firestore free tier. The distributed version (a shared
store such as Memorystore) is the named scale-up seam.
"""

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from src.config import RATE_LIMIT_RPM, RATE_LIMIT_TPM, RATE_LIMIT_WINDOW_SECONDS

# An untouched bucket fully re-earns its request budget within one window; after two it is
# indistinguishable from a fresh one (barring an extreme token overshoot), so evicting it
# under memory pressure is behaviorally lossless.
_STALE_AFTER_WINDOWS: Final[int] = 2


def resolve_client_ip(forwarded_for: str | None, peer_host: str | None) -> str:
    """The caller's IP for rate-limit keying: rightmost ``X-Forwarded-For`` entry, else peer.

    The RIGHTMOST entry is the one Google's front end appends for the peer that actually
    opened the connection, so it cannot be spoofed; leading entries are caller-supplied
    headers and trivially forged. The ``api.`` origin is DNS-only (no proxy in front), so
    that peer IS the real client. Direct local dev has no XFF at all - the socket peer is
    the answer there.
    """
    if forwarded_for:
        entries = [entry.strip() for entry in forwarded_for.split(",") if entry.strip()]
        if entries:
            return entries[-1]
    return peer_host or "unknown"


@dataclass
class _Bucket:
    """One IP's budgets. ``refreshed`` is the clock reading of the last refill."""

    requests_remaining: float
    tokens_remaining: float
    refreshed: float


@dataclass(frozen=True)
class RateLimitDecision:
    """The admission verdict for one request, headers included.

    ``headers`` speaks the limit/remaining/reset vocabulary for both budgets; a denial
    additionally carries ``Retry-After``. ``client_ip`` rides along so the inquiry
    endpoints can debit the same key after the run.
    """

    client_ip: str
    allowed: bool
    retry_after_seconds: int
    headers: dict[str, str]


class RateLimiter:
    """Per-IP token-bucket limiter over two budgets: requests and model tokens.

    A bucket starts full (bursts up to the whole window's quota) and refills steadily at
    ``quota / window`` per second. One ``threading.Lock`` guards the store: the sync
    handlers run on FastAPI's worker threadpool while the stream handler runs on the event
    loop, and a plain lock (held only for arithmetic, never I/O) is correct for both.
    ``clock`` is injectable so tests control time.
    """

    def __init__(
        self,
        *,
        requests_per_window: int,
        tokens_per_window: int,
        window_seconds: float,
        max_tracked_ips: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if requests_per_window <= 0 or tokens_per_window <= 0 or window_seconds <= 0:
            raise ValueError("rate-limit quotas and window must be positive")
        self._requests_per_window: Final[int] = requests_per_window
        self._tokens_per_window: Final[int] = tokens_per_window
        self._window_seconds: Final[float] = window_seconds
        self._request_rate: Final[float] = requests_per_window / window_seconds
        self._token_rate: Final[float] = tokens_per_window / window_seconds
        self._max_tracked_ips: Final[int] = max_tracked_ips
        self._clock: Final[Callable[[], float]] = clock
        self._lock = threading.Lock()
        self._buckets: dict[str, _Bucket] = {}

    @property
    def tracked_ip_count(self) -> int:
        """How many IPs currently hold a bucket (bounded by ``max_tracked_ips``)."""
        with self._lock:
            return len(self._buckets)

    def check_and_reserve(self, client_ip: str) -> RateLimitDecision:
        """Admit or refuse one request: debits 1 from the request budget on admission.

        The token budget is only CHECKED here (exhausted -> deny); it is debited after
        the run via :meth:`debit_tokens`, per the overshoot semantics in the module doc.
        """
        now = self._clock()
        with self._lock:
            bucket = self._bucket_for(client_ip, now)
            if bucket.requests_remaining < 1.0:
                retry = _seconds_until(1.0 - bucket.requests_remaining, self._request_rate)
                return self._denied(client_ip, bucket, retry)
            if bucket.tokens_remaining <= 0.0:
                retry = _seconds_until(1.0 - bucket.tokens_remaining, self._token_rate)
                return self._denied(client_ip, bucket, retry)
            bucket.requests_remaining -= 1.0
            return RateLimitDecision(
                client_ip=client_ip,
                allowed=True,
                retry_after_seconds=0,
                headers=self._build_headers(bucket),
            )

    def debit_tokens(self, client_ip: str, tokens: int) -> None:
        """Charge a finished run's actual token usage against its caller's budget."""
        if tokens <= 0:
            return
        now = self._clock()
        with self._lock:
            bucket = self._bucket_for(client_ip, now)
            bucket.tokens_remaining -= float(tokens)

    def _bucket_for(self, client_ip: str, now: float) -> _Bucket:
        """Get-or-create the IP's bucket, refilled to ``now``. Caller holds the lock."""
        bucket = self._buckets.get(client_ip)
        if bucket is not None:
            elapsed = max(0.0, now - bucket.refreshed)
            bucket.requests_remaining = min(
                float(self._requests_per_window),
                bucket.requests_remaining + elapsed * self._request_rate,
            )
            bucket.tokens_remaining = min(
                float(self._tokens_per_window),
                bucket.tokens_remaining + elapsed * self._token_rate,
            )
            bucket.refreshed = now
            return bucket
        self._evict_if_full(now)
        bucket = _Bucket(
            requests_remaining=float(self._requests_per_window),
            tokens_remaining=float(self._tokens_per_window),
            refreshed=now,
        )
        self._buckets[client_ip] = bucket
        return bucket

    def _evict_if_full(self, now: float) -> None:
        """Keep the store bounded against IP-churn floods. Caller holds the lock.

        Stale buckets (idle >= two windows) are dropped first - behaviorally lossless.
        If the map is still saturated with active IPs, the least-recently-seen one goes;
        it would re-enter with a full budget, a small forgiveness that buys the hard
        memory bound.
        """
        if len(self._buckets) < self._max_tracked_ips:
            return
        cutoff = now - _STALE_AFTER_WINDOWS * self._window_seconds
        stale = [ip for ip, bucket in self._buckets.items() if bucket.refreshed <= cutoff]
        for ip in stale:
            del self._buckets[ip]
        if len(self._buckets) >= self._max_tracked_ips:
            oldest = min(self._buckets, key=lambda ip: self._buckets[ip].refreshed)
            del self._buckets[oldest]

    def _denied(self, client_ip: str, bucket: _Bucket, retry: int) -> RateLimitDecision:
        headers = self._build_headers(bucket)
        headers["Retry-After"] = str(retry)
        return RateLimitDecision(
            client_ip=client_ip, allowed=False, retry_after_seconds=retry, headers=headers
        )

    def _build_headers(self, bucket: _Bucket) -> dict[str, str]:
        """Limit/remaining/reset for both budgets; reset = seconds until fully replenished."""
        request_deficit = float(self._requests_per_window) - bucket.requests_remaining
        token_deficit = float(self._tokens_per_window) - bucket.tokens_remaining
        return {
            "X-RateLimit-Limit-Requests": str(self._requests_per_window),
            "X-RateLimit-Remaining-Requests": str(max(0, math.floor(bucket.requests_remaining))),
            "X-RateLimit-Reset-Requests": str(
                0 if request_deficit <= 0 else _seconds_until(request_deficit, self._request_rate)
            ),
            "X-RateLimit-Limit-Tokens": str(self._tokens_per_window),
            "X-RateLimit-Remaining-Tokens": str(max(0, math.floor(bucket.tokens_remaining))),
            "X-RateLimit-Reset-Tokens": str(
                0 if token_deficit <= 0 else _seconds_until(token_deficit, self._token_rate)
            ),
        }


def _seconds_until(deficit: float, per_second: float) -> int:
    """Whole seconds until steady refill covers ``deficit`` (floor 1: never 'retry now')."""
    return max(1, math.ceil(deficit / per_second))


# The application-wide limiter, parameterized from config like every other constant.
# app.py resolves this name at call time, so tests can swap in a scratch instance.
rate_limiter = RateLimiter(
    requests_per_window=RATE_LIMIT_RPM,
    tokens_per_window=RATE_LIMIT_TPM,
    window_seconds=RATE_LIMIT_WINDOW_SECONDS,
)
