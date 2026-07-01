import type { AgentResult } from "../types/api";
import { formatLatency, formatTokens } from "./format";

function Stat({ label, value, title }: { label: string; value: string; title?: string }) {
  return (
    <div className="flex flex-col" title={title}>
      <span className="text-[0.65rem] uppercase tracking-wide text-fg-subtle">{label}</span>
      <span className="font-mono text-xs text-fg-muted">{value}</span>
    </div>
  );
}

/**
 * The run metadata strip: model and latency, then the billable token split from the `done` event's
 * `AgentResult`. `output_tokens` already includes `thoughts_tokens`, and prompt + output == total
 * (see the AgentTrace contract); the thinking stat notes that it is a subset. All fields degrade to
 * "-" when absent, e.g. a guard run that never called the model.
 */
export function RunMetaStrip({ result }: { result: AgentResult }) {
  return (
    <div className="flex flex-wrap gap-x-6 gap-y-3 border-t border-hairline pt-4">
      <Stat label="Model" value={result.model} />
      <Stat label="Latency" value={formatLatency(result.duration_ms)} />
      <Stat label="Prompt" value={formatTokens(result.prompt_tokens)} />
      <Stat label="Output" value={formatTokens(result.output_tokens)} />
      <Stat
        label="Thinking"
        value={formatTokens(result.thoughts_tokens)}
        title="Reasoning tokens, billed at the output rate and already included in Output."
      />
      <Stat label="Total" value={formatTokens(result.total_tokens)} />
    </div>
  );
}
