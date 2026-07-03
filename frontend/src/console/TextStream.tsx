import { StreamingCaret } from "./StreamingCaret";
import { useTypewriter } from "./useTypewriter";

/**
 * The model's streamed visible answer (`text_delta`), rendered live as the tokens arrive. This is the
 * model's own prose - advisory narration, distinct from and subordinate to the authoritative grounded
 * draft (which rides the terminal `done` result via the draft tool and is never reassembled from these
 * deltas). Presented as plain prose to mirror the draft card; a caret marks the live stream and settles
 * to static text when the run ends. `animate` (Console only) types the text in via `useTypewriter` so
 * coarse `text_delta` chunks read as steady typing. Mount only when `text` is non-empty.
 */
export function TextStream({
  text,
  streaming,
  animate = false,
}: {
  text: string;
  streaming: boolean;
  animate?: boolean;
}) {
  const shown = useTypewriter(text, animate);
  return (
    <section className="mt-6 rounded-xl border border-hairline bg-surface p-5">
      <div className="flex items-center gap-2">
        <h2 className="text-sm font-medium text-fg-muted">Model response</h2>
        <span className="ml-auto text-[0.65rem] uppercase tracking-wide text-fg-subtle">
          Advisory
        </span>
      </div>
      <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed text-fg">
        {shown}
        {streaming ? <StreamingCaret /> : null}
      </p>
    </section>
  );
}
