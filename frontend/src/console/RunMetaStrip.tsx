import { formatLatency, formatTokens } from "./format";

/**
 * The run metrics the strip renders. A structural subset satisfied by both the per-run `AgentResult`
 * (Console, F2) and a persisted `AgentTrace` (Audit Trail, F3), so one strip serves both surfaces.
 * `output_tokens` already includes `thoughts_tokens`, and prompt + output == total.
 */
export interface RunMetrics {
  model: string;
  duration_ms: number | null;
  prompt_tokens: number | null;
  output_tokens: number | null;
  thoughts_tokens: number | null;
  total_tokens: number | null;
}

function Stat({ label, value, title }: { label: string; value: string; title?: string }) {
  return (
    <div className="flex flex-col" title={title}>
      <span className="text-[0.65rem] uppercase tracking-wide text-fg-subtle">{label}</span>
      <span className="font-mono text-xs text-fg-muted">{value}</span>
    </div>
  );
}

/**
 * Model and latency, then the billable token split. The thinking stat notes it is a subset of output
 * (reasoning bills at the output rate). Every field degrades to "-" when absent, e.g. a guard run that
 * never called the model.
 */
export function RunMetaStrip({ metrics }: { metrics: RunMetrics }) {
  return (
    <div className="flex flex-wrap gap-x-6 gap-y-3 border-t border-hairline pt-4">
      <Stat label="Model" value={metrics.model} />
      <Stat label="Latency" value={formatLatency(metrics.duration_ms)} />
      <Stat label="Prompt" value={formatTokens(metrics.prompt_tokens)} />
      <Stat label="Output" value={formatTokens(metrics.output_tokens)} />
      <Stat
        label="Thinking"
        value={formatTokens(metrics.thoughts_tokens)}
        title="Reasoning tokens, billed at the output rate and already included in Output."
      />
      <Stat label="Total" value={formatTokens(metrics.total_tokens)} />
    </div>
  );
}
