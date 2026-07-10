import { useEffect, useRef } from "react";

import { DraftPanel } from "../console/DraftPanel";
import { InquiryForm } from "../console/InquiryForm";
import { PipelineView } from "../console/PipelineView";
import { ReasoningPanel } from "../console/ReasoningPanel";
import { TextStream } from "../console/TextStream";
import { useInquiryRun } from "../console/useInquiryRun";
import { useVendorScope } from "../vendor/VendorScopeContext";

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-fg-subtle">{label}</dt>
      <dd className="mt-0.5 text-fg">{value}</dd>
    </div>
  );
}

function RunError({ message }: { message: string | null }) {
  return (
    <div className="mt-6 rounded-xl border border-danger/40 bg-danger/10 p-5" role="alert">
      <p className="text-sm font-semibold text-danger">The run could not complete</p>
      <p className="mt-1 text-sm text-fg-muted">
        {message ?? "An unexpected error occurred. Please try again."}
      </p>
    </div>
  );
}

/**
 * The analyst console (the hero surface): submit a vendor-scoped inquiry, watch the four-stage agent
 * pipeline stream live over SSE with the model's reasoning and response streaming alongside, then
 * review, decide on, and release the grounded draft. The run state machine (useInquiryRun) turns the
 * stream into the pipeline animation, the Layer-2 reasoning/response surfaces, and the terminal draft;
 * switching vendor scope clears any run so a result never bleeds across vendors.
 *
 * Layout mirrors a chat composer: the inquiry input is pinned to the bottom with the advisory
 * reasoning sitting just above it, while the vendor context, pipeline, model response, and grounded
 * draft scroll in the region above and auto-follow toward the composer as a run streams.
 */
export function ConsolePage() {
  const { selectedVendor, selectedVendorId } = useVendorScope();
  const { state, start, reset } = useInquiryRun();
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    reset();
  }, [selectedVendorId, reset]);

  const running = state.phase === "connecting" || state.phase === "streaming";
  const isTerminal = state.phase === "done" || state.phase === "guarded" || state.phase === "error";
  // Condense the pipeline to a summary once a run settles cleanly (done/guarded); an errored run
  // stays expanded so its partial progress reads alongside the error banner.
  const pipelineCollapsed = state.phase === "done" || state.phase === "guarded";

  // Follow the newest content toward the pinned input as a run streams (Claude-like): the reasoning
  // streams into view just above the composer, then the settled draft takes that spot on completion.
  // Keyed on the content-bearing run state; once terminal these stop changing, so the analyst is
  // free to scroll back up.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [state.phase, state.stages, state.answerText, state.reasoning, state.result]);

  return (
    <section className="flex min-h-0 flex-1 flex-col">
      {/* Scroll region: the vendor context, pipeline, advisory model reasoning/response, and the
          authoritative draft all scroll here, above the pinned input. */}
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto py-8">
        <header className="mb-6 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold text-fg">Console</h1>
            <p className="mt-1 text-sm text-fg-muted">
              Submit an inquiry, watch the agent pipeline run, then review and release the grounded
              draft.
            </p>
          </div>
          {isTerminal ? (
            <button type="button" className="btn btn-ghost" onClick={reset}>
              New inquiry
            </button>
          ) : null}
        </header>

        {selectedVendor ? (
          <div className="mb-6 rounded-xl border border-hairline bg-surface p-5">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <span className="font-mono text-sm text-accent">{selectedVendor.vendor_id}</span>
              <span className="text-sm font-medium text-fg">{selectedVendor.legal_name}</span>
            </div>
            <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 text-xs sm:grid-cols-3">
              <Field label="Country" value={selectedVendor.country} />
              <Field label="Customs broker" value={selectedVendor.customs_broker} />
              <Field label="Categories" value={selectedVendor.categories.join(", ")} />
            </dl>
          </div>
        ) : null}

        {state.phase !== "idle" ? (
          <PipelineView stages={state.stages} guard={state.guard} collapsed={pipelineCollapsed} />
        ) : null}
        {state.answerText ? (
          <TextStream text={state.answerText} streaming={running} animate />
        ) : null}
        {/* Reasoning sits low in the stack - just above the input while a run streams, so the analyst
            watches it think right over the composer; the draft then settles below it on completion. */}
        {state.reasoning ? (
          <ReasoningPanel reasoning={state.reasoning} streaming={running} animate />
        ) : null}
        {state.phase === "error" ? <RunError message={state.error} /> : null}
        {state.result ? (
          <DraftPanel key={state.result.trace_id} result={state.result} guard={state.guard} />
        ) : null}
      </div>

      {/* Pinned composer (Claude-style): only the inquiry input stays fixed at the bottom. */}
      <div className="shrink-0 border-t border-hairline pt-4 pb-6">
        <InquiryForm
          vendorId={selectedVendorId}
          running={running}
          onSubmit={(inquiry) => {
            if (selectedVendorId) start(selectedVendorId, inquiry);
          }}
        />
      </div>
    </section>
  );
}
