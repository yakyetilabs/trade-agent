"""Per-run trace accumulation via :class:`contextvars.ContextVar`.

This is the Python analog of ``AsyncLocalStorage``: the
orchestrator opens a context for the run, each tool appends a :class:`ToolCallLog`
to the *ambient* context as it executes, and the orchestrator reads the
accumulated calls at the end to persist a single :class:`~src.models.AgentTrace`.

Decoupling persistence from the tools (tools only ``append_tool_call``) keeps the
trace atomic and lets the loop attach run-level metadata the tools can't see.

Concurrency note: the stored :class:`TraceContext` is *mutable* and is set before
the agent is invoked, so appends made deep inside the run share the same
``tool_calls`` list. When a tool offloads blocking GCP I/O to a thread, use
``asyncio.to_thread`` (which copies the context) rather than a bare
``run_in_executor`` (which does not) so the ambient context remains visible.
"""

import contextvars
import logging
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.models import ToolCallLog

_logger = logging.getLogger(__name__)


@dataclass
class TraceContext:
    """Mutable per-run trace state accumulated across tool calls."""

    trace_id: str
    vendor_id: str
    tool_calls: list[ToolCallLog] = field(default_factory=list)


_current_trace: contextvars.ContextVar[TraceContext | None] = contextvars.ContextVar(
    "trade_agent_trace", default=None
)


@contextmanager
def trace_context(trace_id: str, vendor_id: str) -> Generator[TraceContext]:
    """Bind a fresh :class:`TraceContext` for the duration of the ``with`` block."""
    ctx = TraceContext(trace_id=trace_id, vendor_id=vendor_id)
    token = _current_trace.set(ctx)
    try:
        yield ctx
    finally:
        _current_trace.reset(token)


def append_tool_call(log: ToolCallLog) -> None:
    """Append a tool-call entry to the active trace.

    If called outside :func:`trace_context` (e.g. a tool invoked directly in a
    unit test), the entry is dropped with a warning rather than raising — tools
    must stay callable without a surrounding run.
    """
    ctx = _current_trace.get()
    if ctx is None:
        _logger.warning("append_tool_call outside trace_context: %s", log.tool_name)
        return
    ctx.tool_calls.append(log)


def get_current_trace() -> TraceContext | None:
    """Return the active :class:`TraceContext`, or ``None`` outside a run."""
    return _current_trace.get()


@contextmanager
def record_tool_call(tool_name: str, tool_input: dict[str, object]) -> Generator[dict[str, object]]:
    """Time a tool invocation and append a :class:`ToolCallLog` on block exit.

    Yields a mutable ``output`` dict the caller fills with a summary of what the
    tool produced. The entry is recorded even if the block raises — the audit
    trail captures the attempt, not just the successes.
    """
    started = time.perf_counter()
    timestamp = datetime.now(UTC).isoformat()
    output: dict[str, object] = {}
    try:
        yield output
    finally:
        append_tool_call(
            ToolCallLog(
                tool_name=tool_name,
                input=tool_input,
                output=dict(output),
                duration_ms=(time.perf_counter() - started) * 1000.0,
                timestamp=timestamp,
            )
        )
