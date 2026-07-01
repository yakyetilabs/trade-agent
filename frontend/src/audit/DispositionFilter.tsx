import type { TraceDisposition } from "../types/api";
import type { DispositionFilterValue } from "./traceView";

const FILTERS: { value: DispositionFilterValue; label: string }[] = [
  { value: "all", label: "All" },
  { value: "draft", label: "Draft" },
  { value: "approved", label: "Approved" },
  { value: "rejected", label: "Rejected" },
  { value: "escalated", label: "Escalated" },
];

interface DispositionFilterProps {
  value: DispositionFilterValue;
  counts: Record<TraceDisposition, number>;
  total: number;
  onChange: (value: DispositionFilterValue) => void;
}

/** Segmented disposition filter with a live count per bucket. Client-side over the loaded page. */
export function DispositionFilter({ value, counts, total, onChange }: DispositionFilterProps) {
  return (
    <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="Filter traces by disposition">
      {FILTERS.map((filter) => {
        const active = filter.value === value;
        const count = filter.value === "all" ? total : counts[filter.value];
        return (
          <button
            key={filter.value}
            type="button"
            role="tab"
            aria-selected={active}
            aria-label={`${filter.label}, ${count} ${count === 1 ? "trace" : "traces"}`}
            onClick={() => onChange(filter.value)}
            className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 ${
              active
                ? "border-accent/60 bg-accent/10 text-fg"
                : "border-hairline bg-surface text-fg-muted hover:bg-elevated hover:text-fg"
            }`}
          >
            {filter.label}
            <span className={`font-mono ${active ? "text-accent" : "text-fg-subtle"}`}>{count}</span>
          </button>
        );
      })}
    </div>
  );
}
