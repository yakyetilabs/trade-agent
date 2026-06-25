"""Unit tests for the ContextVar-based trace accumulation."""

import asyncio
import logging

import pytest

from src.models import ToolCallLog
from src.tracing.trace_context import (
    append_tool_call,
    get_current_trace,
    trace_context,
)


def _log(tool_name: str) -> ToolCallLog:
    return ToolCallLog(
        tool_name=tool_name,
        input={},
        output={},
        duration_ms=1.0,
        timestamp="2026-06-25T00:00:00Z",
    )


def test_no_active_trace_outside_block() -> None:
    assert get_current_trace() is None


def test_context_exposes_ids_accumulates_and_resets() -> None:
    with trace_context("tr-1", "V-001") as ctx:
        assert get_current_trace() is ctx
        assert (ctx.trace_id, ctx.vendor_id) == ("tr-1", "V-001")
        append_tool_call(_log("classify_import_restriction"))
        append_tool_call(_log("draft_clearance_response"))
        assert [c.tool_name for c in ctx.tool_calls] == [
            "classify_import_restriction",
            "draft_clearance_response",
        ]
    # The context is torn down on exit.
    assert get_current_trace() is None


def test_append_outside_context_is_dropped_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        append_tool_call(_log("retrieve_tariff_regulation"))  # no raise
    assert any("outside trace_context" in r.getMessage() for r in caplog.records)


def test_context_propagates_across_await_boundary() -> None:
    # The mutable TraceContext is shared even across an awaited task, mirroring
    # AsyncLocalStorage behavior in Node.
    async def _inner() -> None:
        append_tool_call(_log("lookup_shipment_manifest"))

    with trace_context("tr-async", "V-002") as ctx:
        asyncio.run(_inner())
        assert [c.tool_name for c in ctx.tool_calls] == ["lookup_shipment_manifest"]
