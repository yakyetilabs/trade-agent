import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/api", () => ({ api: { setDisposition: vi.fn() } }));

import type { AgentTrace } from "../types/api";
import { TraceRow } from "./TraceRow";

afterEach(() => {
  vi.clearAllMocks();
});

const trace: AgentTrace = {
  trace_id: "tr-abc",
  timestamp: "2026-07-01T14:30:00Z",
  vendor_id: "V-001",
  user_inquiry: "Why is shipment S-1003 held?",
  classification: {
    intent: "manifest_flag_resolution",
    confidence: 0.9,
    reasoning: "held pending license",
    proposed_hts_heading: null,
    restriction_band: null,
  },
  tool_calls: [
    {
      tool_name: "classify_import_restriction",
      input: { inquiry: "Why is shipment S-1003 held?" },
      output: { intent: "manifest_flag_resolution", confidence: 0.9 },
      duration_ms: 20,
      timestamp: "2026-07-01T14:30:00Z",
    },
  ],
  draft_response: "Shipment S-1003 is held pending an HTS 8542.31.0001 license.",
  thinking_content: "Classify the inquiry, then look up S-1003 and cite the HTS clause before drafting.",
  disposition: "draft",
  model: "gemini-2.5-flash",
  escalation_reason: null,
  duration_ms: 1234,
  prompt_tokens: 100,
  output_tokens: 50,
  thoughts_tokens: 10,
  total_tokens: 150,
};

describe("TraceRow", () => {
  it("shows a collapsed summary and expands to the full detail", async () => {
    const user = userEvent.setup();
    render(<TraceRow trace={trace} vendorName="Meridian Components" onDecided={vi.fn()} />);

    // Collapsed: the intent summary is visible, the inquiry body is not.
    expect(screen.getByText("Manifest flag resolution")).toBeInTheDocument();
    expect(screen.queryByText(/Why is shipment S-1003 held/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Manifest flag resolution/ }));

    // Expanded: the inquiry, the tool timeline, and the maker-checker action all render.
    expect(screen.getByText(/Why is shipment S-1003 held/)).toBeInTheDocument();
    expect(screen.getByText("Classify import restriction")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve & release" })).toBeInTheDocument();
    // Raw tool I/O is available but collapsed by default.
    expect(screen.getByRole("button", { name: "Show raw I/O" })).toBeInTheDocument();
    // The persisted reasoning is offered as a folded disclosure (#15).
    expect(screen.getByRole("button", { name: /Reasoning/ })).toBeInTheDocument();
  });
});
