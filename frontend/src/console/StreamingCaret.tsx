/**
 * A blinking cursor bar that marks live token streaming (the typewriter affordance), shared by the
 * reasoning and response surfaces so the streaming cue is identical on both. Purely decorative -
 * `aria-hidden`, so assistive tech reads the streamed text without a spurious glyph - and reuses the
 * theme's `soft-pulse` so the caret breathes in step with the active pipeline node.
 */
export function StreamingCaret() {
  return (
    <span
      data-testid="streaming-caret"
      aria-hidden="true"
      className="ml-0.5 inline-block h-[1em] w-[2px] translate-y-[0.15em] animate-soft-pulse bg-accent align-baseline"
    />
  );
}
