import { useState } from "react";

import { DispositionBadge } from "../console/DispositionBadge";
import { formatLatency, formatTimestamp, formatTokens, humanizeIntent } from "../console/format";
import type { AgentTrace, TraceDisposition } from "../types/api";
import { TraceDetail } from "./TraceDetail";

function ChevronIcon({ open }: { open: boolean }) {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      className={`flex-none text-fg-subtle transition-transform duration-150 ${open ? "rotate-180" : ""}`}
    >
      <path
        d="m6 9 6 6 6-6"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

interface TraceRowProps {
  trace: AgentTrace;
  vendorName: string | null;
  onDecided: (traceId: string, disposition: TraceDisposition) => void;
}

/** One audit-trail row: a collapsed summary that expands to the full trace detail. */
export function TraceRow({ trace, vendorName, onDecided }: TraceRowProps) {
  const [open, setOpen] = useState(false);

  return (
    <div className="overflow-hidden rounded-xl border border-hairline bg-surface">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-elevated/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent/40"
      >
        <DispositionBadge disposition={trace.disposition} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-fg">
            {humanizeIntent(trace.classification?.intent)}
          </span>
          <span className="mt-0.5 block truncate text-xs text-fg-muted">
            <span className="font-mono text-accent">{trace.vendor_id}</span>
            {vendorName ? ` · ${vendorName}` : ""}
          </span>
        </span>
        <span className="hidden flex-none text-right sm:block">
          <span className="block font-mono text-xs text-fg-muted">
            {formatLatency(trace.duration_ms)}
          </span>
          <span className="block text-[0.7rem] text-fg-subtle">
            {formatTokens(trace.total_tokens)} tok
          </span>
        </span>
        <span className="hidden flex-none text-right text-xs text-fg-subtle md:block">
          {formatTimestamp(trace.timestamp)}
        </span>
        <ChevronIcon open={open} />
      </button>
      {open ? <TraceDetail trace={trace} vendorName={vendorName} onDecided={onDecided} /> : null}
    </div>
  );
}
