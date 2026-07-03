import { useEffect, useId, useRef, useState } from "react";

import { StreamingCaret } from "./StreamingCaret";

/** A chevron that rotates to point down when the panel is open. */
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

/**
 * A collapsible disclosure of the model's streamed reasoning (`thinking_delta`) - the "watch it think"
 * surface. Open by default so the reasoning is visible as it streams; the analyst can fold it away.
 * While streaming, a "Thinking" pulse shows and the well auto-follows the newest thought (log-tail).
 * Advisory only: the reasoning is never part of the authoritative grounded draft. Reused by the Audit
 * Trail's trace detail to render the persisted `thinking_content` (static, `streaming={false}`, and
 * `defaultOpen={false}` so it stays folded in the dense record). Mount only when `reasoning` is set.
 */
export function ReasoningPanel({
  reasoning,
  streaming,
  defaultOpen = true,
}: {
  reasoning: string;
  streaming: boolean;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const regionId = useId();
  const scrollRef = useRef<HTMLDivElement>(null);

  // Keep the freshest reasoning in view while it streams in, like tailing a log.
  useEffect(() => {
    if (streaming && open && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [reasoning, streaming, open]);

  return (
    <section className="mt-6 rounded-xl border border-hairline bg-surface p-5">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-controls={regionId}
          className="flex items-center gap-2 rounded text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50"
        >
          <Chevron open={open} />
          <span className="text-sm font-medium text-fg-muted">Reasoning</span>
        </button>
        {streaming ? (
          <span className="flex items-center gap-1.5 text-xs text-accent">
            <span
              className="h-1.5 w-1.5 animate-soft-pulse rounded-full bg-accent"
              aria-hidden="true"
            />
            Thinking
          </span>
        ) : null}
        <span className="ml-auto text-[0.65rem] uppercase tracking-wide text-fg-subtle">
          Advisory
        </span>
      </div>

      {open ? (
        <div
          id={regionId}
          ref={scrollRef}
          className="mt-3 max-h-64 overflow-y-auto rounded-lg border border-hairline bg-ink/50 p-3"
        >
          <p className="whitespace-pre-wrap text-xs leading-relaxed text-fg-muted">
            {reasoning}
            {streaming ? <StreamingCaret /> : null}
          </p>
        </div>
      ) : null}
    </section>
  );
}
