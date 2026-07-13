import { useState } from "react";

import type { AgentResult, TraceDisposition } from "../types/api";
import { CitedDraft } from "./CitedDraft";
import { DispositionActions } from "./DispositionActions";
import { DispositionBadge } from "./DispositionBadge";
import type { GuardOutcome } from "./useInquiryRun";
import { RunMetaStrip } from "./RunMetaStrip";
import { useTypewriter } from "./useTypewriter";

/**
 * The terminal panel for a finished run. A grounded draft settles into a document card with cited
 * chips, the maker-checker actions (Approve/Reject while it is still a draft; a recorded badge once
 * decided), and the run metadata strip. Edit opens a local working copy - drafts are disposition-only
 * by design, so edits are never persisted. A guard or draft-less run shows a routed/empty state with
 * the same metadata strip. Mount this keyed by `result.trace_id` so its state is fresh per run.
 */
export function DraftPanel({ result, guard }: { result: AgentResult; guard: GuardOutcome | null }) {
  const pristine = result.draft_response ?? "";
  const [disposition, setDisposition] = useState<TraceDisposition>(result.disposition);
  const [editing, setEditing] = useState(false);
  const [draftText, setDraftText] = useState(pristine);
  const [copied, setCopied] = useState(false);
  // Type the grounded draft out on first paint (this panel is keyed by trace id, so each run gets a
  // fresh reveal). The reveal is presentational only - the authoritative text is `pristine`, still
  // used verbatim for copy/edit/approve; the draft is never reassembled from stream deltas.
  const revealed = useTypewriter(pristine, true);

  const hasDraft = pristine !== "";
  const isEdited = draftText !== pristine;

  async function copy() {
    try {
      await navigator.clipboard.writeText(draftText);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard unavailable (e.g. an insecure context) - the visible text is still selectable.
    }
  }

  if (!hasDraft) {
    return (
      <div className="mt-6 rounded-xl border border-hairline bg-surface p-5">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-sm font-medium text-fg-muted">No draft produced</h2>
          <DispositionBadge disposition={disposition} />
        </div>
        <p className="mt-3 text-sm text-fg-muted">
          {guard
            ? "This inquiry was routed to a human reviewer before the model ran."
            : "The run finished without generating a draft."}
        </p>
        <div className="mt-4">
          <RunMetaStrip metrics={result} />
        </div>
      </div>
    );
  }

  return (
    <div className="mt-6 rounded-xl border border-hairline bg-surface p-5">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-medium text-fg-muted">Grounded draft</h2>
        <DispositionBadge disposition={disposition} />
      </div>

      {editing ? (
        <>
          <textarea
            value={draftText}
            onChange={(event) => setDraftText(event.target.value)}
            rows={10}
            aria-label="Draft working copy"
            className="mt-3 w-full resize-y rounded-lg border border-hairline bg-elevated px-3 py-2.5 text-sm leading-relaxed text-fg focus-visible:border-accent/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
          />
          <p className="mt-2 text-xs text-fg-subtle">
            Local working copy - not saved. Drafts are disposition-only by design; approve or reject
            to record a decision.
          </p>
        </>
      ) : (
        <div className="mt-3">
          <CitedDraft text={isEdited ? draftText : revealed} />
          {isEdited ? <p className="mt-2 text-xs text-fg-subtle">Edited locally.</p> : null}
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-hairline pt-4">
        {disposition === "draft" ? (
          <DispositionActions
            traceId={result.trace_id}
            actionable={result.draft_actionable}
            onDecided={setDisposition}
          />
        ) : null}
        <div className="ml-auto flex items-center gap-2">
          <button type="button" className="btn btn-ghost" onClick={() => setEditing((v) => !v)}>
            {editing ? "Done" : "Edit"}
          </button>
          <button type="button" className="btn btn-ghost" onClick={() => void copy()}>
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
      </div>

      <div className="mt-4">
        <RunMetaStrip metrics={result} />
      </div>
    </div>
  );
}
