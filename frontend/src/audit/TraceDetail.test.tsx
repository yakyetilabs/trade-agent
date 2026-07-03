import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/api", () => ({ api: { setDisposition: vi.fn() } }));

import type { AgentTrace } from "../types/api";
import { TraceDetail } from "./TraceDetail";

afterEach(() => {
  vi.clearAllMocks();
});

function trace(overrides: Partial<AgentTrace>): AgentTrace {
  return {
    trace_id: "tr-1",
    timestamp: "2026-07-01T14:30:00Z",
    vendor_id: "V-001",
    user_inquiry: "why held?",
    classification: null,
    tool_calls: [],
    draft_response: "Shipment S-1003 is held pending a license.",
    thinking_content: null,
    disposition: "draft",
    model: "gemini-2.5-flash",
    escalation_reason: null,
    duration_ms: 1200,
    prompt_tokens: 100,
    output_tokens: 50,
    thoughts_tokens: 10,
    total_tokens: 150,
    ...overrides,
  };
}

describe("TraceDetail", () => {
  it("surfaces the persisted reasoning as a folded disclosure that expands on demand", async () => {
    const user = userEvent.setup();
    render(
      <TraceDetail
        trace={trace({ thinking_content: "Classify first, then look up S-1003 before drafting." })}
        vendorName="Meridian Components"
        onDecided={vi.fn()}
      />,
    );

    // Collapsed by default in the dense audit record: the reasoning body is not yet in the DOM.
    const toggle = screen.getByRole("button", { name: /Reasoning/ });
    expect(screen.queryByText(/Classify first, then look up/)).not.toBeInTheDocument();

    await user.click(toggle);
    expect(screen.getByText(/Classify first, then look up/)).toBeInTheDocument();
  });

  it("omits the reasoning disclosure when the trace carries no thinking_content", () => {
    render(
      <TraceDetail trace={trace({ thinking_content: null })} vendorName={null} onDecided={vi.fn()} />,
    );
    expect(screen.queryByRole("button", { name: /Reasoning/ })).not.toBeInTheDocument();
  });
});
