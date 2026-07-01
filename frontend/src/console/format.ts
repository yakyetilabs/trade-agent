/**
 * Small pure presentation helpers shared across the Console: humanizing the classifier intent, and
 * formatting latency and token counts for the metadata strip and pipeline summaries.
 */
import type { InquiryIntent } from "../types/api";

/** "manifest_flag_resolution" -> "Manifest flag resolution". Enum-agnostic (works for any intent). */
export function humanizeIntent(intent: InquiryIntent | null | undefined): string {
  if (!intent) return "Unknown";
  const spaced = intent.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** A confidence in [0, 1] as a whole-number percent ("92%"); "-" when absent. */
export function formatConfidence(confidence: number | null | undefined): string {
  if (confidence === null || confidence === undefined) return "-";
  return `${Math.round(confidence * 100)}%`;
}

/** Milliseconds as a compact duration: "440 ms" under a second, else "1.2 s". "-" when absent. */
export function formatLatency(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "-";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

/** A token count with thousands separators; "-" when the backend reported none (e.g. a guard run). */
export function formatTokens(count: number | null | undefined): string {
  if (count === null || count === undefined) return "-";
  return count.toLocaleString("en-US");
}
