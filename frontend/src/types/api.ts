/**
 * TypeScript mirror of the backend's public API contracts - the single source of shape truth for
 * the frontend. Every type here corresponds to a Pydantic model or endpoint payload in
 * backend/src/models.py, backend/src/agent.py, backend/src/app.py, and backend/src/streaming.py.
 *
 * String-literal unions match the backend StrEnum wire values verbatim (Pydantic dumps enum
 * members as their plain string). Fields declared `X | None` on the backend appear as `X | null`.
 */

// --- Enumerations (backend StrEnums; values are the wire form) -----------------------------------

export type GoodsCategory =
  | "electronics"
  | "textiles"
  | "agriculture"
  | "machinery"
  | "pharmaceuticals"
  | "chemicals";

export type RestrictionLevel = "unrestricted" | "license_required" | "quota_controlled" | "prohibited";

export type ShipmentStatus = "in_transit" | "held" | "flagged" | "cleared";

/** The first four are model-classifiable; the last two are system-injected by the guards/loop. */
export type InquiryIntent =
  | "tariff_lookup"
  | "manifest_flag_resolution"
  | "clearance_requirements"
  | "unknown"
  | "cross_vendor_refusal"
  | "iteration_cap_exceeded";

/** The agent only ever writes `draft`/`escalated`; a human reviewer sets `approved`/`rejected`. */
export type TraceDisposition = "draft" | "escalated" | "approved" | "rejected";

// --- Domain + run models -------------------------------------------------------------------------

export interface Vendor {
  vendor_id: string;
  legal_name: string;
  country: string;
  customs_broker: string;
  categories: GoodsCategory[];
  active: boolean;
}

export interface ImportClassification {
  intent: InquiryIntent;
  confidence: number;
  reasoning: string;
  proposed_hts_heading: string | null;
  restriction_band: RestrictionLevel | null;
}

export interface ToolCallLog {
  tool_name: string;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  duration_ms: number;
  timestamp: string;
}

/** The single audit document per run (GET /api/traces). Token fields are the billable split:
 *  `output_tokens` already includes `thoughts_tokens`, and prompt + output == total. */
export interface AgentTrace {
  trace_id: string;
  timestamp: string;
  vendor_id: string;
  user_inquiry: string;
  classification: ImportClassification | null;
  tool_calls: ToolCallLog[];
  draft_response: string | null;
  disposition: TraceDisposition;
  model: string;
  escalation_reason: string | null;
  duration_ms: number | null;
  prompt_tokens: number | null;
  output_tokens: number | null;
  thoughts_tokens: number | null;
  total_tokens: number | null;
}

/** The lean per-run projection returned by POST /api/inquiry and carried by the SSE `done` event. */
export interface AgentResult {
  trace_id: string;
  disposition: TraceDisposition;
  draft_response: string | null;
  classification: ImportClassification | null;
  tool_call_count: number;
  tool_names: string[];
  duration_ms: number;
  model: string;
  escalation_reason: string | null;
  prompt_tokens: number | null;
  output_tokens: number | null;
  thoughts_tokens: number | null;
  total_tokens: number | null;
}

// --- Endpoint request/response payloads ----------------------------------------------------------

export interface IdentityResponse {
  email: string;
  authorized: boolean;
}

export interface InquiryRequest {
  vendor_id: string;
  inquiry: string;
}

/** The only caller-settable dispositions - `draft`/`escalated` are agent-written, never posted. */
export type DispositionDecision = "approved" | "rejected";

export interface DispositionResponse {
  trace_id: string;
  disposition: TraceDisposition;
}

// --- Layer-1 SSE event contract (backend/src/streaming.py) ---------------------------------------
// The wire form is an `event: <name>` line + a `data: <json>` line; the name is not in the JSON.
// The F2 stream reader pairs them into these tagged variants (the `type` tag = the SSE event name).

export type PipelineStage = "classify" | "lookup" | "retrieve" | "draft";

export type GuardKind = "escalation" | "cross_vendor";

/** Per-stage `stage_completed` summaries - the same compact projection recorded on the audit trace
 *  (backend _stage_summary). Fields are optional/nullable because a degraded tool yields an
 *  empty-ish summary rather than failing the stream. */
export interface ClassifyStageSummary {
  intent?: InquiryIntent | null;
  confidence?: number | null;
}
export interface LookupStageSummary {
  count?: number | null;
  shipment_ids?: string[];
}
export interface RetrieveStageSummary {
  hts_codes?: string[];
  exact_hit?: boolean;
}
export interface DraftStageSummary {
  ready?: boolean;
}

export interface RunStartedEvent {
  trace_id: string;
  vendor_id: string;
  model: string;
}
export interface StageStartedEvent {
  stage: PipelineStage;
}
export interface GuardTriggeredEvent {
  kind: GuardKind;
  reason: string | null;
}
export interface DoneEvent {
  result: AgentResult;
}
export interface ErrorEvent {
  message: string;
}

/** `stage_completed` is discriminated by `stage` so F2 can narrow each summary exhaustively. */
export type StageCompletedEvent =
  | { stage: "classify"; summary: ClassifyStageSummary }
  | { stage: "lookup"; summary: LookupStageSummary }
  | { stage: "retrieve"; summary: RetrieveStageSummary }
  | { stage: "draft"; summary: DraftStageSummary };

/** The full stream vocabulary, discriminated by `type` (= the SSE `event:` name). */
export type StreamEvent =
  | ({ type: "run_started" } & RunStartedEvent)
  | ({ type: "stage_started" } & StageStartedEvent)
  | ({ type: "stage_completed" } & StageCompletedEvent)
  | ({ type: "guard_triggered" } & GuardTriggeredEvent)
  | ({ type: "done" } & DoneEvent)
  | ({ type: "error" } & ErrorEvent);
