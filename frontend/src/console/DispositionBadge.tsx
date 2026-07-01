import type { TraceDisposition } from "../types/api";

const TONE: Record<TraceDisposition, { dot: string; text: string; label: string }> = {
  draft: { dot: "bg-warn", text: "text-warn", label: "Draft" },
  escalated: { dot: "bg-danger", text: "text-danger", label: "Escalated" },
  approved: { dot: "bg-success", text: "text-success", label: "Approved" },
  rejected: { dot: "bg-danger", text: "text-danger", label: "Rejected" },
};

/** A small status pill for a trace disposition - a colored dot + label. Reused by the Audit Trail. */
export function DispositionBadge({ disposition }: { disposition: TraceDisposition }) {
  const tone = TONE[disposition];
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-hairline bg-elevated px-2.5 py-1 text-xs font-medium">
      <span className={`h-2 w-2 rounded-full ${tone.dot}`} aria-hidden="true" />
      <span className={tone.text}>{tone.label}</span>
    </span>
  );
}
