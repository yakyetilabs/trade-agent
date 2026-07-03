/**
 * The Console's run-state machine: a pure reducer over the SSE event stream, plus the hook that
 * drives it.
 *
 * The reducer folds the `StreamEvent` union (src/types/api.ts) into a view model the Console renders:
 * a phase (idle -> connecting -> streaming -> done | guarded | error), the four pipeline stages with
 * their live status and completed summaries, the accumulated Layer-2 model output (`reasoning` from
 * `thinking_delta`, `answerText` from `text_delta`), an optional guard outcome, and the terminal
 * `AgentResult`. It is exported and framework-free so the transitions are unit-tested without any
 * network. `useInquiryRun` owns the `AbortController` and feeds `streamInquiry` events into it.
 */
import { useCallback, useEffect, useReducer, useRef } from "react";

import { getFirebaseIdToken } from "../lib/firebase";
import { streamInquiry } from "../lib/inquiryStream";
import type {
  AgentResult,
  ClassifyStageSummary,
  DraftStageSummary,
  GuardKind,
  LookupStageSummary,
  PipelineStage,
  RetrieveStageSummary,
  StreamEvent,
} from "../types/api";

export type RunPhase = "idle" | "connecting" | "streaming" | "guarded" | "done" | "error";

export type StageStatus = "pending" | "active" | "complete" | "skipped";

/** The fixed left-to-right pipeline order the Console renders (the locked four-tool contract). */
export const STAGE_ORDER: readonly PipelineStage[] = ["classify", "lookup", "retrieve", "draft"];

/** Each stage carries its live status and, once complete, the typed summary from `stage_completed`. */
export interface RunStages {
  classify: { status: StageStatus; summary: ClassifyStageSummary | null };
  lookup: { status: StageStatus; summary: LookupStageSummary | null };
  retrieve: { status: StageStatus; summary: RetrieveStageSummary | null };
  draft: { status: StageStatus; summary: DraftStageSummary | null };
}

export interface GuardOutcome {
  kind: GuardKind;
  reason: string | null;
}

export interface RunState {
  phase: RunPhase;
  traceId: string | null;
  model: string | null;
  stages: RunStages;
  /** Accumulated `thinking_delta` fragments - the model's streamed reasoning (advisory). */
  reasoning: string;
  /** Accumulated `text_delta` fragments - the model's streamed visible answer (advisory). */
  answerText: string;
  guard: GuardOutcome | null;
  result: AgentResult | null;
  error: string | null;
}

export type RunAction =
  | { type: "submit" }
  | { type: "event"; event: StreamEvent }
  | { type: "fail"; message: string }
  | { type: "reset" };

function freshStages(): RunStages {
  return {
    classify: { status: "pending", summary: null },
    lookup: { status: "pending", summary: null },
    retrieve: { status: "pending", summary: null },
    draft: { status: "pending", summary: null },
  };
}

function freshRun(phase: RunPhase): RunState {
  return {
    phase,
    traceId: null,
    model: null,
    stages: freshStages(),
    reasoning: "",
    answerText: "",
    guard: null,
    result: null,
    error: null,
  };
}

export const initialRunState: RunState = freshRun("idle");

function withStageActive(stages: RunStages, stage: PipelineStage): RunStages {
  switch (stage) {
    case "classify":
      return { ...stages, classify: { ...stages.classify, status: "active" } };
    case "lookup":
      return { ...stages, lookup: { ...stages.lookup, status: "active" } };
    case "retrieve":
      return { ...stages, retrieve: { ...stages.retrieve, status: "active" } };
    case "draft":
      return { ...stages, draft: { ...stages.draft, status: "active" } };
  }
}

/** Mark a stage complete and attach its typed summary. `event` is narrowed per stage by its tag. */
function withStageComplete(
  stages: RunStages,
  event: Extract<StreamEvent, { type: "stage_completed" }>,
): RunStages {
  switch (event.stage) {
    case "classify":
      return { ...stages, classify: { status: "complete", summary: event.summary } };
    case "lookup":
      return { ...stages, lookup: { status: "complete", summary: event.summary } };
    case "retrieve":
      return { ...stages, retrieve: { status: "complete", summary: event.summary } };
    case "draft":
      return { ...stages, draft: { status: "complete", summary: event.summary } };
  }
}

/** On a terminal event, a stage the agent never invoked reads as "skipped" rather than stuck pending. */
function markUnusedSkipped(stages: RunStages): RunStages {
  const skip = (status: StageStatus): StageStatus => (status === "pending" ? "skipped" : status);
  return {
    classify: { ...stages.classify, status: skip(stages.classify.status) },
    lookup: { ...stages.lookup, status: skip(stages.lookup.status) },
    retrieve: { ...stages.retrieve, status: skip(stages.retrieve.status) },
    draft: { ...stages.draft, status: skip(stages.draft.status) },
  };
}

function applyEvent(state: RunState, event: StreamEvent): RunState {
  switch (event.type) {
    case "run_started":
      return { ...state, phase: "streaming", traceId: event.trace_id, model: event.model };
    case "stage_started":
      return { ...state, stages: withStageActive(state.stages, event.stage) };
    case "stage_completed":
      return { ...state, stages: withStageComplete(state.stages, event) };
    case "thinking_delta":
      return { ...state, reasoning: state.reasoning + event.text };
    case "text_delta":
      return { ...state, answerText: state.answerText + event.text };
    case "guard_triggered":
      return { ...state, guard: { kind: event.kind, reason: event.reason } };
    case "done":
      return {
        ...state,
        result: event.result,
        phase: state.guard ? "guarded" : "done",
        stages: markUnusedSkipped(state.stages),
      };
    case "error":
      return { ...state, phase: "error", error: event.message };
    default:
      return state;
  }
}

export function inquiryRunReducer(state: RunState, action: RunAction): RunState {
  switch (action.type) {
    case "submit":
      return freshRun("connecting");
    case "event":
      return applyEvent(state, action.event);
    case "fail":
      return { ...state, phase: "error", error: action.message };
    case "reset":
      return freshRun("idle");
  }
}

export interface InquiryRunController {
  state: RunState;
  /** Start a streamed run for the given vendor + inquiry, superseding any run already in flight. */
  start: (vendorId: string, inquiry: string) => void;
  /** Abort any in-flight run and return to idle. */
  reset: () => void;
}

export function useInquiryRun(): InquiryRunController {
  const [state, dispatch] = useReducer(inquiryRunReducer, initialRunState);
  const abortRef = useRef<AbortController | null>(null);

  const start = useCallback((vendorId: string, inquiry: string) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    dispatch({ type: "submit" });

    void (async () => {
      try {
        for await (const event of streamInquiry({
          vendorId,
          inquiry,
          getToken: getFirebaseIdToken,
          signal: controller.signal,
        })) {
          if (controller.signal.aborted) return;
          dispatch({ type: "event", event });
        }
      } catch (err) {
        if (controller.signal.aborted) return; // superseded or unmounted - not a user-facing failure
        dispatch({
          type: "fail",
          message: err instanceof Error ? err.message : "The inquiry stream failed.",
        });
      }
    })();
  }, []);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    dispatch({ type: "reset" });
  }, []);

  // Abort a run still in flight when the Console unmounts.
  useEffect(() => () => abortRef.current?.abort(), []);

  return { state, start, reset };
}
