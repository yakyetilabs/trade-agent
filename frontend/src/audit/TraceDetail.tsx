import { type ReactNode } from "react";

import { CitedDraft } from "../console/CitedDraft";
import { DispositionActions } from "../console/DispositionActions";
import { DispositionBadge } from "../console/DispositionBadge";
import { formatConfidence, formatTimestamp, humanizeIntent } from "../console/format";
import { RunMetaStrip } from "../console/RunMetaStrip";
import type { AgentTrace, TraceDisposition } from "../types/api";
import { ToolTimeline } from "./ToolTimeline";

function MetaField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[0.65rem] uppercase tracking-wide text-fg-subtle">{label}</dt>
      <dd className="mt-0.5 truncate text-fg">{children}</dd>
    </div>
  );
}

interface TraceDetailProps {
  trace: AgentTrace;
  vendorName: string | null;
  onDecided: (traceId: string, disposition: TraceDisposition) => void;
}

/**
 * The expanded audit record for one run: the inquiry, the run metadata, the recorded tool timeline,
 * the grounded draft (cited identically to the Console), the billable token split, and the
 * maker-checker control - Approve/Reject while it is still a draft, else the recorded disposition.
 */
export function TraceDetail({ trace, vendorName, onDecided }: TraceDetailProps) {
  const draft = trace.draft_response;

  return (
    <div className="border-t border-hairline bg-ink/30 px-4 py-5 sm:px-5">
      <p className="border-l-2 border-hairline pl-3 text-sm italic leading-relaxed text-fg-muted">
        {trace.user_inquiry}
      </p>

      <dl className="mt-5 grid grid-cols-2 gap-x-6 gap-y-4 text-xs sm:grid-cols-4">
        <MetaField label="Vendor">
          <span className="font-mono text-accent">{trace.vendor_id}</span>
          {vendorName ? <span className="ml-1.5 text-fg-muted">{vendorName}</span> : null}
        </MetaField>
        <MetaField label="Intent">
          {humanizeIntent(trace.classification?.intent)}
          {trace.classification ? (
            <span className="ml-1 text-fg-subtle">
              · {formatConfidence(trace.classification.confidence)}
            </span>
          ) : null}
        </MetaField>
        <MetaField label="Submitted">{formatTimestamp(trace.timestamp)}</MetaField>
        <MetaField label="Trace ID">
          <span className="font-mono text-fg-muted">{trace.trace_id}</span>
        </MetaField>
      </dl>

      <section className="mt-6">
        <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-fg-subtle">
          Tool timeline
        </h3>
        <ToolTimeline toolCalls={trace.tool_calls} />
      </section>

      <section className="mt-6">
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-fg-subtle">
          {draft ? "Draft response" : "Outcome"}
        </h3>
        {draft ? (
          <div className="rounded-lg border border-hairline bg-surface p-4">
            <CitedDraft text={draft} />
          </div>
        ) : (
          <p className="text-sm text-fg-muted">
            {trace.escalation_reason
              ? `Escalated before the model ran: ${trace.escalation_reason}`
              : "No draft was produced for this run."}
          </p>
        )}
      </section>

      <div className="mt-6">
        <RunMetaStrip metrics={trace} />
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-3 border-t border-hairline pt-4">
        {trace.disposition === "draft" ? (
          <DispositionActions
            traceId={trace.trace_id}
            onDecided={(disposition) => onDecided(trace.trace_id, disposition)}
          />
        ) : (
          <div className="flex items-center gap-2 text-xs text-fg-muted">
            <span>Recorded disposition:</span>
            <DispositionBadge disposition={trace.disposition} />
          </div>
        )}
      </div>
    </div>
  );
}
