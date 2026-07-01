import { describe, expect, it } from "vitest";

import type { AgentTrace, ToolCallLog } from "../types/api";
import { countByDisposition, filterTracesByDisposition, summarizeToolCall } from "./traceView";

function trace(overrides: Partial<AgentTrace>): AgentTrace {
  return {
    trace_id: "tr-1",
    timestamp: "2026-07-01T00:00:00Z",
    vendor_id: "V-001",
    user_inquiry: "why held?",
    classification: null,
    tool_calls: [],
    draft_response: null,
    disposition: "draft",
    model: "gemini-2.5-flash",
    escalation_reason: null,
    duration_ms: 100,
    prompt_tokens: null,
    output_tokens: null,
    thoughts_tokens: null,
    total_tokens: null,
    ...overrides,
  };
}

function call(
  toolName: string,
  input: Record<string, unknown>,
  output: Record<string, unknown>,
): ToolCallLog {
  return { tool_name: toolName, input, output, duration_ms: 12, timestamp: "2026-07-01T00:00:00Z" };
}

describe("filterTracesByDisposition", () => {
  const traces = [
    trace({ trace_id: "a", disposition: "draft" }),
    trace({ trace_id: "b", disposition: "approved" }),
  ];

  it("returns everything when the filter is 'all'", () => {
    expect(filterTracesByDisposition(traces, "all")).toHaveLength(2);
  });

  it("filters to a single disposition", () => {
    expect(filterTracesByDisposition(traces, "approved").map((t) => t.trace_id)).toEqual(["b"]);
  });
});

describe("countByDisposition", () => {
  it("counts each bucket", () => {
    const counts = countByDisposition([
      trace({ disposition: "draft" }),
      trace({ disposition: "draft" }),
      trace({ disposition: "approved" }),
    ]);
    expect(counts).toEqual({ draft: 2, escalated: 0, approved: 1, rejected: 0 });
  });
});

describe("summarizeToolCall", () => {
  it("summarizes classify with humanized intent and confidence", () => {
    const view = summarizeToolCall(
      call(
        "classify_import_restriction",
        { inquiry: "x" },
        { intent: "manifest_flag_resolution", confidence: 0.92 },
      ),
    );
    expect(view.stage).toBe("classify");
    expect(view.title).toBe("Classify import restriction");
    expect(view.output).toBe("Manifest flag resolution · 92%");
    expect(view.scopeViolation).toBe(false);
  });

  it("summarizes a lookup and lists the shipment ids", () => {
    const view = summarizeToolCall(
      call(
        "lookup_shipment_manifest",
        { shipment_id: "S-1003" },
        { count: 1, shipment_ids: ["S-1003"], scope_violation: false },
      ),
    );
    expect(view.input).toBe("S-1003");
    expect(view.output).toBe("1 shipment: S-1003");
  });

  it("flags a lookup scope violation", () => {
    const view = summarizeToolCall(
      call(
        "lookup_shipment_manifest",
        { shipment_id: "S-9999" },
        { count: 0, shipment_ids: [], scope_violation: true },
      ),
    );
    expect(view.scopeViolation).toBe(true);
    expect(view.output).toMatch(/scope violation/i);
  });

  it("summarizes retrieve with the exact-hit count and codes", () => {
    const view = summarizeToolCall(
      call(
        "retrieve_tariff_regulation",
        { query: "HTS 8542.31.0001", k: 5 },
        { chunk_count: 2, exact_hits: 1, hts_codes: ["8542.31.0001", "8541.10.0000"] },
      ),
    );
    expect(view.input).toBe("HTS 8542.31.0001");
    expect(view.output).toBe("2 clauses, 1 exact: 8542.31.0001, 8541.10.0000");
  });

  it("summarizes the draft with citation counts", () => {
    const view = summarizeToolCall(
      call(
        "draft_clearance_response",
        { cited_hts_codes: ["8542.31.0001"], cited_shipment_ids: ["S-1003"], confidence: 0.9 },
        { status: "drafted", trace_id: "tr-1" },
      ),
    );
    expect(view.input).toBe("Cites 1 HTS · 1 shipment · conf 90%");
    expect(view.output).toBe("Draft recorded");
  });

  it("falls back to a generic view for an unknown tool", () => {
    const view = summarizeToolCall(call("mystery_probe", { foo: "bar" }, { baz: 3 }));
    expect(view.stage).toBeNull();
    expect(view.title).toBe("Mystery probe");
    expect(view.input).toBe("foo: bar");
    expect(view.output).toBe("baz: 3");
  });
});
