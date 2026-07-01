import { useState } from "react";

import { api } from "../lib/api";
import type { DispositionDecision, TraceDisposition } from "../types/api";

interface DispositionActionsProps {
  traceId: string;
  /** Called with the recorded disposition once the backend confirms the decision. */
  onDecided: (disposition: TraceDisposition) => void;
}

/**
 * The maker-checker decision on a draft trace: Approve and release, or Reject. Both POST to
 * /api/traces/{id}/disposition (the only caller-settable dispositions). The buttons lock while a
 * decision is in flight; a failure surfaces inline and leaves the trace a draft to retry.
 */
export function DispositionActions({ traceId, onDecided }: DispositionActionsProps) {
  const [pending, setPending] = useState<DispositionDecision | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function decide(decision: DispositionDecision) {
    setPending(decision);
    setError(null);
    try {
      const response = await api.setDisposition(traceId, decision);
      onDecided(response.disposition);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not record the decision.");
    } finally {
      setPending(null);
    }
  }

  const busy = pending !== null;

  return (
    <div className="flex flex-wrap items-center gap-2">
      <button
        type="button"
        className="btn btn-primary"
        disabled={busy}
        onClick={() => void decide("approved")}
      >
        {pending === "approved" ? "Approving…" : "Approve & release"}
      </button>
      <button
        type="button"
        className="btn btn-ghost hover:border-danger/50 hover:text-danger"
        disabled={busy}
        onClick={() => void decide("rejected")}
      >
        {pending === "rejected" ? "Rejecting…" : "Reject"}
      </button>
      {error ? (
        <span className="text-xs text-danger" role="alert">
          {error}
        </span>
      ) : null}
    </div>
  );
}
