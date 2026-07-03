import { useId, useState } from "react";

import type { PipelineStage } from "../types/api";
import { formatConfidence, humanizeIntent } from "./format";
import type { GuardOutcome, RunStages, StageStatus } from "./useInquiryRun";
import { STAGE_ORDER } from "./useInquiryRun";

const STAGE_LABEL: Record<PipelineStage, string> = {
  classify: "Classify",
  lookup: "Look up",
  retrieve: "Retrieve",
  draft: "Draft",
};

const STAGE_HINT: Record<PipelineStage, string> = {
  classify: "Intent + confidence",
  lookup: "Shipment manifests",
  retrieve: "Tariff clauses",
  draft: "Clearance response",
};

const GUARD_LABEL: Record<GuardOutcome["kind"], string> = {
  escalation: "escalation guard",
  cross_vendor: "cross-vendor guard",
};

/** A short monospace citation chip, shared by the pipeline summaries and the draft body. */
function Chip({ children }: { children: string }) {
  return (
    <span className="inline-block rounded bg-elevated px-1.5 py-0.5 font-mono text-[0.72rem] leading-tight text-accent">
      {children}
    </span>
  );
}

function CheckIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="m5 13 4 4L19 7"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

const NODE_RING: Record<StageStatus, string> = {
  pending: "border-hairline text-fg-subtle",
  active: "border-accent text-accent animate-soft-pulse",
  complete: "border-success/60 bg-success/10 text-success",
  skipped: "border-hairline/60 text-fg-subtle opacity-60",
};

/** The per-stage completed summary - the same projection the audit trace records. */
function StageSummary({ stage, stages }: { stage: PipelineStage; stages: RunStages }) {
  if (stage === "classify") {
    const { summary } = stages.classify;
    return (
      <span className="text-fg-muted">
        {humanizeIntent(summary?.intent)} · {formatConfidence(summary?.confidence)}
      </span>
    );
  }
  if (stage === "lookup") {
    const { summary } = stages.lookup;
    const ids = summary?.shipment_ids ?? [];
    const shown = ids.slice(0, 3);
    return (
      <span className="flex flex-wrap items-center gap-1 text-fg-muted">
        {summary?.count ?? 0} shipment{summary?.count === 1 ? "" : "s"}
        {shown.map((id) => (
          <Chip key={id}>{id}</Chip>
        ))}
        {ids.length > shown.length ? <span>+{ids.length - shown.length}</span> : null}
      </span>
    );
  }
  if (stage === "retrieve") {
    const { summary } = stages.retrieve;
    const codes = summary?.hts_codes ?? [];
    return (
      <span className="flex flex-wrap items-center gap-1 text-fg-muted">
        {codes.length > 0 ? (
          codes.slice(0, 3).map((code) => <Chip key={code}>{code}</Chip>)
        ) : (
          <span>no codes</span>
        )}
        {summary?.exact_hit ? <span className="text-success">exact</span> : null}
      </span>
    );
  }
  const { summary } = stages.draft;
  return <span className="text-fg-muted">{summary?.ready ? "Ready" : "-"}</span>;
}

function StageNode({
  stage,
  index,
  stages,
}: {
  stage: PipelineStage;
  index: number;
  stages: RunStages;
}) {
  const { status } = stages[stage];
  return (
    <li className="flex min-w-0 flex-1 items-start gap-3 sm:flex-col sm:items-stretch">
      <div className="flex items-center gap-3 sm:flex-col sm:items-start">
        <span className="relative flex-none">
          {status === "active" ? (
            <span className="absolute inset-0 animate-ping rounded-full border border-accent/50" />
          ) : null}
          <span
            className={`relative flex h-8 w-8 items-center justify-center rounded-full border text-xs font-semibold ${NODE_RING[status]}`}
          >
            {status === "complete" ? <CheckIcon /> : index + 1}
          </span>
        </span>
      </div>
      <div className="min-w-0">
        <p
          className={`text-sm font-medium ${status === "pending" || status === "skipped" ? "text-fg-subtle" : "text-fg"}`}
        >
          {STAGE_LABEL[stage]}
        </p>
        <div className="mt-0.5 text-xs">
          {status === "complete" ? (
            <StageSummary stage={stage} stages={stages} />
          ) : (
            <span className="text-fg-subtle">
              {status === "skipped" ? "Not used" : STAGE_HINT[stage]}
            </span>
          )}
        </div>
      </div>
    </li>
  );
}

const STAGE_DOT: Record<StageStatus, string> = {
  pending: "bg-fg-subtle/40",
  active: "bg-accent",
  complete: "bg-success",
  skipped: "bg-fg-subtle/40",
};

/** A chevron that rotates to point down when the disclosure opens (matches ReasoningPanel). */
function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      className={`flex-none text-fg-subtle transition-transform duration-150 ease-out-soft ${open ? "rotate-90" : ""}`}
    >
      <path
        d="m9 6 6 6-6 6"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** The deterministic-guard banner. The model never ran, so it leads the pipeline card in both the
 *  live and the collapsed layouts. */
function GuardBanner({ guard }: { guard: GuardOutcome }) {
  return (
    <div className="mt-3 rounded-lg border border-danger/40 bg-danger/10 p-4" role="status">
      <p className="text-sm font-semibold text-danger">Routed to a human reviewer</p>
      <p className="mt-1 text-xs leading-relaxed text-fg-muted">
        Intercepted by the deterministic {GUARD_LABEL[guard.kind]} before the model ran - no tokens
        were spent.
      </p>
      {guard.reason ? (
        <p className="mt-2 border-l-2 border-danger/40 pl-2 text-xs italic text-fg-subtle">
          {guard.reason}
        </p>
      ) : null}
    </div>
  );
}

/** A terse one-line projection of the completed run for the collapsed header (intent + confidence,
 *  shipment count, the exact HTS hit). Empty when a guard pre-empted the model (no stage summaries). */
function condensedSummary(stages: RunStages): string {
  const parts: string[] = [];

  const classify = stages.classify.summary;
  if (classify?.intent) {
    parts.push(`${humanizeIntent(classify.intent)} · ${formatConfidence(classify.confidence)}`);
  }

  const lookup = stages.lookup.summary;
  if (lookup && lookup.count != null) {
    parts.push(`${lookup.count} shipment${lookup.count === 1 ? "" : "s"}`);
  }

  const firstCode = stages.retrieve.summary?.hts_codes?.[0];
  if (firstCode) {
    parts.push(stages.retrieve.summary?.exact_hit ? `${firstCode} exact` : firstCode);
  }

  return parts.join(" · ");
}

interface PipelineViewProps {
  stages: RunStages;
  guard: GuardOutcome | null;
  /** Once the run settles, fold the four-node card into a click-to-expand summary. This keeps the
   *  live animation as the hero while streaming, then stops the settled per-stage detail from
   *  duplicating the /traces audit view (see the PipelineView docblock). */
  collapsed?: boolean;
}

/**
 * The collapsed pipeline shown once a run settles: a compact header (four status dots + a one-line
 * result summary) folding the full four-node card into a disclosure that defaults closed. A fired
 * guard still leads with its banner; the all-skipped stages tuck inside the disclosure.
 */
function CollapsedPipelineView({ stages, guard }: PipelineViewProps) {
  const [open, setOpen] = useState(false);
  const regionId = useId();
  const summary = condensedSummary(stages);

  return (
    <div className="mt-6 rounded-xl border border-hairline bg-surface p-5">
      {guard ? <GuardBanner guard={guard} /> : null}
      <div className={guard ? "mt-4" : ""}>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            aria-controls={regionId}
            className="flex items-center gap-2 rounded text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50"
          >
            <Chevron open={open} />
            <span className="text-sm font-medium text-fg-muted">Pipeline</span>
          </button>
          <span className="flex items-center gap-1.5">
            {STAGE_ORDER.map((stage) => (
              <span
                key={stage}
                title={`${STAGE_LABEL[stage]}: ${stages[stage].status}`}
                aria-hidden="true"
                className={`h-1.5 w-1.5 rounded-full ${STAGE_DOT[stages[stage].status]}`}
              />
            ))}
          </span>
          {summary ? <span className="text-xs text-fg-subtle">{summary}</span> : null}
        </div>

        {open ? (
          <ol id={regionId} className="mt-4 flex flex-col gap-4 sm:flex-row sm:gap-3">
            {STAGE_ORDER.map((stage, index) => (
              <StageNode key={stage} stage={stage} index={index} stages={stages} />
            ))}
          </ol>
        ) : null}
      </div>
    </div>
  );
}

interface FullPipelineViewProps {
  stages: RunStages;
  guard: GuardOutcome | null;
}

/**
 * The four-stage agent pipeline. While a run streams (`collapsed` false) each node animates
 * pending -> active (soft pulse) -> complete with its real summary, or reads "Not used" when the
 * agent skipped that tool, and a fired pre-model guard leads with a banner. Once the run settles,
 * `collapsed` hands off to `CollapsedPipelineView` so the settled detail - already recorded in full
 * by the /traces audit view - folds into a disclosure instead of duplicating that page.
 */
export function PipelineView({ stages, guard, collapsed = false }: PipelineViewProps) {
  if (collapsed) {
    return <CollapsedPipelineView stages={stages} guard={guard} />;
  }
  return <FullPipelineView stages={stages} guard={guard} />;
}

function FullPipelineView({ stages, guard }: FullPipelineViewProps) {
  return (
    <div className="mt-6 rounded-xl border border-hairline bg-surface p-5">
      <h2 className="text-sm font-medium text-fg-muted">Pipeline</h2>

      {guard ? <GuardBanner guard={guard} /> : null}

      <ol className="mt-4 flex flex-col gap-4 sm:flex-row sm:gap-3">
        {STAGE_ORDER.map((stage, index) => (
          <StageNode key={stage} stage={stage} index={index} stages={stages} />
        ))}
      </ol>
    </div>
  );
}
