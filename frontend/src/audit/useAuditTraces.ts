import { useCallback, useEffect, useState } from "react";

import { api } from "../lib/api";
import type { AgentTrace, TraceDisposition } from "../types/api";

interface AuditTracesState {
  traces: AgentTrace[];
  loading: boolean;
  error: string | null;
}

export interface AuditTraces extends AuditTracesState {
  reload: () => void;
  /** Patch one trace's disposition in place after a human decision, so the row + detail update
   *  without a full refetch (the backend already recorded it). */
  applyDisposition: (traceId: string, disposition: TraceDisposition) => void;
}

/**
 * Load the analyst's recent audit traces (`GET /api/traces` - newest first, scope-filtered
 * server-side) and hold them for the Audit Trail. The list is scope-wide, not tied to the Console's
 * selected vendor, so it is fetched once on mount and only refetched on an explicit `reload`.
 */
export function useAuditTraces(): AuditTraces {
  const [state, setState] = useState<AuditTracesState>({ traces: [], loading: true, error: null });

  const load = useCallback(async () => {
    setState((prev) => ({ ...prev, loading: true, error: null }));
    try {
      const traces = await api.listTraces();
      setState({ traces, loading: false, error: null });
    } catch (err) {
      setState({
        traces: [],
        loading: false,
        error: err instanceof Error ? err.message : String(err),
      });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const applyDisposition = useCallback((traceId: string, disposition: TraceDisposition) => {
    setState((prev) => ({
      ...prev,
      traces: prev.traces.map((trace) =>
        trace.trace_id === traceId ? { ...trace, disposition } : trace,
      ),
    }));
  }, []);

  return { ...state, reload: load, applyDisposition };
}
