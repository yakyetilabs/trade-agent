import { useMemo, useState } from "react";

import { DispositionFilter } from "../audit/DispositionFilter";
import { TraceRow } from "../audit/TraceRow";
import {
  countByDisposition,
  type DispositionFilterValue,
  filterTracesByDisposition,
} from "../audit/traceView";
import { useAuditTraces } from "../audit/useAuditTraces";
import { Spinner } from "../components/Spinner";
import { useVendorScope } from "../vendor/VendorScopeContext";

/**
 * Audit Trail (`/traces`): the recent-runs record. A disposition-filtered list of traces, each
 * expandable to its full detail - the inquiry, the four-tool timeline, the grounded draft, the token
 * split, and the maker-checker control. Traces are scope-wide (every vendor the analyst is authorized
 * for), so this reads independently of the Console's selected vendor.
 */
export function AuditTrailPage() {
  const { vendors } = useVendorScope();
  const { traces, loading, error, reload, applyDisposition } = useAuditTraces();
  const [filter, setFilter] = useState<DispositionFilterValue>("all");

  const vendorNames = useMemo(() => {
    const map = new Map<string, string>();
    for (const vendor of vendors) map.set(vendor.vendor_id, vendor.legal_name);
    return map;
  }, [vendors]);

  const counts = useMemo(() => countByDisposition(traces), [traces]);
  const filtered = useMemo(() => filterTracesByDisposition(traces, filter), [traces, filter]);

  return (
    // Owns its own scroll now that the shell is height-bounded and `main` drops its padding.
    <section className="min-h-0 flex-1 overflow-y-auto py-8">
      <header className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-fg">Audit Trail</h1>
          <p className="mt-1 text-sm text-fg-muted">
            Every run, recorded: disposition, intent, latency, the billable token split, and the full
            tool-call timeline.
          </p>
        </div>
        {!loading && !error ? (
          <button type="button" className="btn btn-ghost" onClick={reload}>
            Refresh
          </button>
        ) : null}
      </header>

      {loading ? (
        <div className="flex justify-center py-16">
          <Spinner label="Loading traces" />
        </div>
      ) : error ? (
        <div className="rounded-xl border border-danger/40 bg-danger/10 p-5" role="alert">
          <p className="text-sm font-semibold text-danger">Could not load the audit trail</p>
          <p className="mt-1 text-sm text-fg-muted">{error}</p>
          <button type="button" className="btn btn-ghost mt-4" onClick={reload}>
            Try again
          </button>
        </div>
      ) : traces.length === 0 ? (
        <div className="rounded-xl border border-dashed border-hairline bg-surface/40 p-10 text-center">
          <p className="text-sm text-fg-muted">No runs recorded yet.</p>
          <p className="mt-1 text-sm text-fg-subtle">
            Submit an inquiry from the Console and it will appear here.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          <DispositionFilter
            value={filter}
            counts={counts}
            total={traces.length}
            onChange={setFilter}
          />
          {filtered.length === 0 ? (
            <p className="py-8 text-center text-sm text-fg-subtle">
              No {filter} traces in the recent window.
            </p>
          ) : (
            <div className="space-y-3">
              {filtered.map((trace) => (
                <TraceRow
                  key={trace.trace_id}
                  trace={trace}
                  vendorName={vendorNames.get(trace.vendor_id) ?? null}
                  onDecided={applyDisposition}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
