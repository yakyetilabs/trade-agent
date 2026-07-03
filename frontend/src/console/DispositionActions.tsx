import { useState } from "react";

import { api } from "../lib/api";
import type { DispositionDecision, TraceDisposition } from "../types/api";

interface DispositionActionsProps {
  traceId: string;
  /** Whether the draft is a releasable clearance response. When false, Approve is withheld -
   *  approving a "no shipment found / cannot provide" result makes no sense - and only Reject
   *  is offered so the analyst can still close the trace out. */
  actionable: boolean;
  /** Called with the recorded disposition once the backend confirms the decision. */
  onDecided: (disposition: TraceDisposition) => void;
}

/**
 * The maker-checker decision on a draft trace: Approve and release, or Reject. Both POST to
 * /api/traces/{id}/disposition (the only caller-settable dispositions). The buttons lock while a
 * decision is in flight; a failure surfaces inline and leaves the trace a draft to retry. When the
 * draft is not actionable, Approve is replaced by a short "nothing to release" note (Reject stays).
 */
export function DispositionActions({ traceId, actionable, onDecided }: DispositionActionsProps) {
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
      {actionable ? (
        <button
          type="button"
          className="btn btn-primary"
          disabled={busy}
          onClick={() => void decide("approved")}
        >
          {pending === "approved" ? "Approving…" : "Approve & release"}
        </button>
      ) : (
        <span className="text-xs text-fg-subtle" role="note">
          No clearable shipment - nothing to approve.
        </span>
      )}
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
