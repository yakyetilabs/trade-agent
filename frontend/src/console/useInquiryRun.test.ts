import { describe, expect, it } from "vitest";

import type { AgentResult, StreamEvent } from "../types/api";
import { inquiryRunReducer, initialRunState, type RunState } from "./useInquiryRun";

const RESULT: AgentResult = {
  trace_id: "tr-1",
  disposition: "draft",
  draft_response: "Draft body.",
  draft_actionable: true,
  classification: null,
  tool_call_count: 4,
  tool_names: ["classify_import_restriction"],
  duration_ms: 1200,
  model: "gemini-2.5-flash",
  escalation_reason: null,
  prompt_tokens: 100,
  output_tokens: 20,
  thoughts_tokens: 5,
  total_tokens: 120,
};

/** Fold a sequence of events over a submitted run, as the hook does. */
function play(events: StreamEvent[]): RunState {
  let state = inquiryRunReducer(initialRunState, { type: "submit" });
  for (const event of events) state = inquiryRunReducer(state, { type: "event", event });
  return state;
}

describe("inquiryRunReducer", () => {
  it("submit resets to a fresh connecting run", () => {
    const dirty = inquiryRunReducer(initialRunState, {
      type: "event",
      event: { type: "error", message: "boom" },
    });
    const state = inquiryRunReducer(dirty, { type: "submit" });
    expect(state.phase).toBe("connecting");
    expect(state.error).toBeNull();
    expect(state.result).toBeNull();
    expect(state.stages.classify.status).toBe("pending");
  });

  it("run_started moves to streaming and records trace + model", () => {
    const state = play([
      { type: "run_started", trace_id: "tr-1", vendor_id: "V-001", model: "gemini-2.5-flash" },
    ]);
    expect(state.phase).toBe("streaming");
    expect(state.traceId).toBe("tr-1");
    expect(state.model).toBe("gemini-2.5-flash");
  });

  it("marks a stage active on start and complete with its typed summary", () => {
    const state = play([
      { type: "run_started", trace_id: "tr-1", vendor_id: "V-001", model: "m" },
      { type: "stage_started", stage: "classify" },
      { type: "stage_completed", stage: "classify", summary: { intent: "tariff_lookup", confidence: 0.9 } },
      { type: "stage_started", stage: "retrieve" },
    ]);
    expect(state.stages.classify.status).toBe("complete");
    expect(state.stages.classify.summary).toEqual({ intent: "tariff_lookup", confidence: 0.9 });
    expect(state.stages.retrieve.status).toBe("active");
  });

  it("accumulates thinking_delta into reasoning and text_delta into answerText, in arrival order", () => {
    const state = play([
      { type: "run_started", trace_id: "tr-1", vendor_id: "V-001", model: "m" },
      { type: "thinking_delta", text: "Class" },
      { type: "thinking_delta", text: "ifying." },
      { type: "text_delta", text: "The shipment " },
      { type: "text_delta", text: "is held." },
    ]);
    expect(state.reasoning).toBe("Classifying.");
    expect(state.answerText).toBe("The shipment is held.");
  });

  it("keeps accumulated reasoning and answerText through the done event", () => {
    const state = play([
      { type: "run_started", trace_id: "tr-1", vendor_id: "V-001", model: "m" },
      { type: "thinking_delta", text: "thought" },
      { type: "text_delta", text: "answer" },
      { type: "done", result: RESULT },
    ]);
    expect(state.phase).toBe("done");
    expect(state.reasoning).toBe("thought");
    expect(state.answerText).toBe("answer");
  });

  it("submit clears reasoning and answerText from a prior run", () => {
    const dirty = play([
      { type: "run_started", trace_id: "tr-1", vendor_id: "V-001", model: "m" },
      { type: "thinking_delta", text: "old" },
      { type: "text_delta", text: "old" },
    ]);
    const state = inquiryRunReducer(dirty, { type: "submit" });
    expect(state.reasoning).toBe("");
    expect(state.answerText).toBe("");
  });

  it("on done, completes to done and marks never-started stages skipped", () => {
    const state = play([
      { type: "run_started", trace_id: "tr-1", vendor_id: "V-001", model: "m" },
      { type: "stage_started", stage: "classify" },
      { type: "stage_completed", stage: "classify", summary: { intent: "tariff_lookup" } },
      { type: "done", result: RESULT },
    ]);
    expect(state.phase).toBe("done");
    expect(state.result).toEqual(RESULT);
    expect(state.stages.classify.status).toBe("complete");
    expect(state.stages.lookup.status).toBe("skipped");
    expect(state.stages.draft.status).toBe("skipped");
  });

  it("a guard then done yields the guarded phase with the guard outcome", () => {
    const state = play([
      { type: "run_started", trace_id: "tr-1", vendor_id: "V-001", model: "m" },
      { type: "guard_triggered", kind: "escalation", reason: "OFAC match" },
      { type: "done", result: { ...RESULT, disposition: "escalated", draft_response: null } },
    ]);
    expect(state.phase).toBe("guarded");
    expect(state.guard).toEqual({ kind: "escalation", reason: "OFAC match" });
    expect(state.stages.classify.status).toBe("skipped");
  });

  it("an error event moves to the error phase with the message", () => {
    const state = play([{ type: "error", message: "Unknown vendor: V-999" }]);
    expect(state.phase).toBe("error");
    expect(state.error).toBe("Unknown vendor: V-999");
  });

  it("a fail action (network drop) moves to the error phase", () => {
    const streaming = play([
      { type: "run_started", trace_id: "tr-1", vendor_id: "V-001", model: "m" },
    ]);
    const state = inquiryRunReducer(streaming, { type: "fail", message: "network down" });
    expect(state.phase).toBe("error");
    expect(state.error).toBe("network down");
  });

  it("reset returns to idle", () => {
    const state = inquiryRunReducer(play([{ type: "error", message: "x" }]), { type: "reset" });
    expect(state).toEqual(initialRunState);
  });
});
