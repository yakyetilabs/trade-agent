import { useState } from "react";

import { formatLatency } from "../console/format";
import type { ToolCallLog } from "../types/api";
import { summarizeToolCall } from "./traceView";

function RawColumn({ label, value }: { label: string; value: Record<string, unknown> }) {
  return (
    <div className="min-w-0">
      <dt className="text-[0.65rem] uppercase tracking-wide text-fg-subtle">{label}</dt>
      <dd>
        <pre className="mt-1 overflow-x-auto rounded-lg border border-hairline bg-ink/60 p-3 font-mono text-[0.7rem] leading-relaxed text-fg-muted">
          {JSON.stringify(value, null, 2)}
        </pre>
      </dd>
    </div>
  );
}

function TimelineItem({ call, index }: { call: ToolCallLog; index: number }) {
  const [rawOpen, setRawOpen] = useState(false);
  const view = summarizeToolCall(call);

  return (
    <li className="flex gap-3">
      <span
        className="mt-0.5 flex h-6 w-6 flex-none items-center justify-center rounded-full border border-hairline bg-elevated font-mono text-[0.7rem] text-fg-muted"
        aria-hidden="true"
      >
        {index + 1}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
          <p className="text-sm font-medium text-fg">{view.title}</p>
          <span className="font-mono text-xs text-fg-subtle">{formatLatency(call.duration_ms)}</span>
        </div>
        <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
          <span className="text-fg-muted">{view.input}</span>
          <span aria-hidden="true" className="text-fg-subtle">
            &rarr;
          </span>
          <span className={view.scopeViolation ? "font-medium text-danger" : "text-fg"}>
            {view.output}
          </span>
        </p>
        <button
          type="button"
          onClick={() => setRawOpen((open) => !open)}
          aria-expanded={rawOpen}
          className="mt-2 text-[0.7rem] font-medium text-fg-subtle underline-offset-2 hover:text-fg-muted hover:underline"
        >
          {rawOpen ? "Hide raw I/O" : "Show raw I/O"}
        </button>
        {rawOpen ? (
          <dl className="mt-2 grid gap-2 sm:grid-cols-2">
            <RawColumn label="Input" value={call.input} />
            <RawColumn label="Output" value={call.output} />
          </dl>
        ) : null}
      </div>
    </li>
  );
}

/**
 * The recorded four-tool timeline for a trace: each call's humanized name, duration, and a one-line
 * input-to-output summary, with a per-call raw I/O disclosure for full audit fidelity. A guarded run
 * has no tool calls and says so.
 */
export function ToolTimeline({ toolCalls }: { toolCalls: ToolCallLog[] }) {
  if (toolCalls.length === 0) {
    return (
      <p className="text-sm text-fg-subtle">
        No tools were called - this inquiry was routed before the model ran.
      </p>
    );
  }
  return (
    <ol className="space-y-5">
      {toolCalls.map((call, index) => (
        <TimelineItem key={`${call.tool_name}-${index}`} call={call} index={index} />
      ))}
    </ol>
  );
}
