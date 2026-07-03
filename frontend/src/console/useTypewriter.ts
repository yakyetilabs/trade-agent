import { useEffect, useRef, useState } from "react";

// Reveal cadence. Advance a share of the remaining backlog each frame - an ease-out that always
// catches up - clamped so a large backlog never dumps in a single frame and a tiny one still moves.
// At ~60fps, MAX_STEP=10 tops out near 600 chars/s: fast enough to keep pace with the SSE stream,
// slow enough that a coarse chunk reads as typing rather than a lurch.
const REVEAL_FACTOR = 0.2;
const MIN_STEP = 1;
const MAX_STEP = 10;

/**
 * Pure: the revealed length after one animation frame, growing `shownLen` toward `targetLen`.
 * The step is proportional to the remaining backlog (so bursts drain fast and the tail eases in),
 * clamped to [MIN_STEP, MAX_STEP]. Returns `targetLen` once caught up - or clamps back to it if a
 * shrunk target left us past the end. Framework-free so the cadence is unit-tested without rAF.
 */
export function nextRevealLength(shownLen: number, targetLen: number): number {
  if (shownLen >= targetLen) return targetLen;
  const remaining = targetLen - shownLen;
  const step = Math.min(MAX_STEP, Math.max(MIN_STEP, Math.ceil(remaining * REVEAL_FACTOR)));
  return Math.min(targetLen, shownLen + step);
}

/**
 * Smoothly reveal `target` a few characters per animation frame so a coarsely-chunked stream (Gemini
 * emits thoughts/text a sentence or paragraph at a time) reads as steady typing instead of lurching in
 * blocks. This decouples render cadence from network arrival - the underlying SSE is untouched, and the
 * full `target` is always available to callers (copy, approve, edit all use it, not the revealed slice).
 *
 * - `animate=false` renders the full `target` immediately: the static audit-trail render, and the
 *   default, so existing non-animated usages are byte-identical.
 * - While animating, a `requestAnimationFrame` loop advances the reveal and stops once caught up; each
 *   growth of `target` (a new streamed chunk) re-arms it from where it left off.
 *
 * Surfaces that reset per run (the Console remounts the reasoning/response panels when their text
 * empties and keys the draft by trace id) get a fresh reveal from the mount, so no cross-run carryover.
 */
export function useTypewriter(target: string, animate: boolean): string {
  const [shownLen, setShownLen] = useState(() => (animate ? 0 : target.length));
  // Mirror the committed length so the rAF loop advances monotonically even across frames that fire
  // before React commits, and so scheduling stays out of the (possibly double-invoked) state updater.
  const lenRef = useRef(shownLen);
  lenRef.current = shownLen;

  useEffect(() => {
    if (!animate) {
      setShownLen(target.length);
      return;
    }
    let frame = 0;
    const tick = () => {
      const next = nextRevealLength(lenRef.current, target.length);
      lenRef.current = next;
      setShownLen(next);
      if (next < target.length) {
        frame = requestAnimationFrame(tick);
      }
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [target, animate]);

  return target.slice(0, shownLen);
}
