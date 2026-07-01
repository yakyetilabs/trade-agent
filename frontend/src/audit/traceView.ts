/**
 * Pure, framework-free projections for the Audit Trail (F3): disposition filtering/counts and the
 * per-tool timeline summary. Kept free of React so it is unit-tested directly (mirrors the F2
 * `citations`/`format` discipline). The timeline summaries read the SAME raw input/output dicts the
 * backend persists on each `ToolCallLog` (see the four tools in `backend/src/tools/`); unknown tools
 * fall back to a generic key rendering rather than throwing.
 */
import { formatConfidence, humanizeIntent } from "../console/format";
import type { AgentTrace, InquiryIntent, PipelineStage, ToolCallLog, TraceDisposition } from "../types/api";

// --- disposition filtering -----------------------------------------------------------------------

export type DispositionFilterValue = "all" | TraceDisposition;

export function filterTracesByDisposition(
  traces: AgentTrace[],
  filter: DispositionFilterValue,
): AgentTrace[] {
  return filter === "all" ? traces : traces.filter((trace) => trace.disposition === filter);
}

export function countByDisposition(traces: AgentTrace[]): Record<TraceDisposition, number> {
  const counts: Record<TraceDisposition, number> = {
    draft: 0,
    escalated: 0,
    approved: 0,
    rejected: 0,
  };
  for (const trace of traces) counts[trace.disposition] += 1;
  return counts;
}

// --- per-tool timeline projection ----------------------------------------------------------------

// The locked four-tool contract mapped to the four pipeline stages (matches the backend
// TOOL_TO_STAGE in src/streaming.py). Keys are the `@tool` function names.
const TOOL_STAGE: Record<string, PipelineStage> = {
  classify_import_restriction: "classify",
  lookup_shipment_manifest: "lookup",
  retrieve_tariff_regulation: "retrieve",
  draft_clearance_response: "draft",
};

const TOOL_LABEL: Record<string, string> = {
  classify_import_restriction: "Classify import restriction",
  lookup_shipment_manifest: "Look up shipment manifest",
  retrieve_tariff_regulation: "Retrieve tariff regulation",
  draft_clearance_response: "Draft clearance response",
};

/** A compact, human view of one recorded tool call: a title plus a one-line "input -> output". */
export interface ToolCallView {
  stage: PipelineStage | null;
  title: string;
  input: string;
  output: string;
  /** Surfaced from the lookup tool's audit flag; a foreign-shipment attempt renders in danger. */
  scopeViolation: boolean;
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" ? value : null;
}

function asStringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function asIntent(value: unknown): InquiryIntent | null {
  // humanizeIntent treats it as a plain string; the cast only satisfies its narrower param type.
  return typeof value === "string" ? (value as InquiryIntent) : null;
}

function truncate(text: string, max = 90): string {
  const trimmed = text.trim();
  return trimmed.length > max ? `${trimmed.slice(0, max - 1)}…` : trimmed;
}

function joinIds(ids: string[], max = 4): string {
  if (ids.length === 0) return "";
  const shown = ids.slice(0, max).join(", ");
  return ids.length > max ? `${shown} +${ids.length - max}` : shown;
}

function humanizeToolName(name: string): string {
  const spaced = name.replace(/_/g, " ").trim();
  return spaced ? spaced.charAt(0).toUpperCase() + spaced.slice(1) : name;
}

function formatUnknownValue(value: unknown): string {
  if (Array.isArray(value)) return `[${value.length}]`;
  if (value !== null && typeof value === "object") return "{…}";
  return String(value);
}

/** Generic fallback for a tool this projection does not know: a compact `key: value` join. */
function compactKeys(record: Record<string, unknown>): string {
  const entries = Object.entries(record).filter(
    ([, value]) => value !== null && value !== undefined && value !== "",
  );
  if (entries.length === 0) return "-";
  return entries.map(([key, value]) => `${key}: ${formatUnknownValue(value)}`).join(", ");
}

/**
 * Project one recorded tool call into a compact, human one-line summary for the timeline. Reads the
 * same input/output dicts the backend persists; every read is defensive (`asString`/`asNumber`) so a
 * degraded or shape-drifted call renders best-effort rather than throwing.
 */
export function summarizeToolCall(call: ToolCallLog): ToolCallView {
  const stage = TOOL_STAGE[call.tool_name] ?? null;
  const title = TOOL_LABEL[call.tool_name] ?? humanizeToolName(call.tool_name);
  const { input, output } = call;

  switch (call.tool_name) {
    case "classify_import_restriction": {
      const heading = asString(output.proposed_hts_heading);
      const band = asString(output.restriction_band);
      const proposal = heading ? ` · proposes ${heading}${band ? ` (${band})` : ""}` : "";
      return {
        stage,
        title,
        input: "Analyst inquiry",
        output: `${humanizeIntent(asIntent(output.intent))} · ${formatConfidence(asNumber(output.confidence))}${proposal}`,
        scopeViolation: false,
      };
    }
    case "lookup_shipment_manifest": {
      const filters: string[] = [];
      const shipmentId = asString(input.shipment_id);
      const status = asString(input.status);
      const dateFrom = asString(input.date_from);
      const dateTo = asString(input.date_to);
      if (shipmentId) filters.push(shipmentId);
      if (status) filters.push(`status ${status}`);
      if (dateFrom) filters.push(`from ${dateFrom}`);
      if (dateTo) filters.push(`to ${dateTo}`);
      const scopeViolation = output.scope_violation === true;
      const count = asNumber(output.count) ?? 0;
      const ids = asStringList(output.shipment_ids);
      return {
        stage,
        title,
        input: filters.length > 0 ? filters.join(", ") : "All shipments",
        output: scopeViolation
          ? "Scope violation - foreign shipment blocked"
          : `${count} shipment${count === 1 ? "" : "s"}${ids.length > 0 ? `: ${joinIds(ids)}` : ""}`,
        scopeViolation,
      };
    }
    case "retrieve_tariff_regulation": {
      const query = asString(input.query);
      const codes = asStringList(output.hts_codes);
      const count = asNumber(output.chunk_count) ?? codes.length;
      const exact = asNumber(output.exact_hits) ?? 0;
      const parts = [`${count} clause${count === 1 ? "" : "s"}`];
      if (exact > 0) parts.push(`${exact} exact`);
      return {
        stage,
        title,
        input: query ? truncate(query) : "Regulation query",
        output: `${parts.join(", ")}${codes.length > 0 ? `: ${joinIds(codes)}` : ""}`,
        scopeViolation: false,
      };
    }
    case "draft_clearance_response": {
      const htsCount = asStringList(input.cited_hts_codes).length;
      const shipCount = asStringList(input.cited_shipment_ids).length;
      const confidence = formatConfidence(asNumber(input.confidence));
      return {
        stage,
        title,
        input: `Cites ${htsCount} HTS · ${shipCount} shipment${shipCount === 1 ? "" : "s"} · conf ${confidence}`,
        output: output.status === "drafted" ? "Draft recorded" : (asString(output.status) ?? "-"),
        scopeViolation: false,
      };
    }
    default:
      return {
        stage,
        title,
        input: truncate(compactKeys(input)),
        output: truncate(compactKeys(output)),
        scopeViolation: output.scope_violation === true,
      };
  }
}
