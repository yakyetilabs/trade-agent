import { describe, expect, it } from "vitest";

import { nextRevealLength } from "./useTypewriter";

describe("nextRevealLength", () => {
  it("stays at the target once fully revealed", () => {
    expect(nextRevealLength(5, 5)).toBe(5);
  });

  it("clamps back to the target if somehow past it (a shrunk target)", () => {
    expect(nextRevealLength(8, 5)).toBe(5);
  });

  it("caps a large backlog so no single frame dumps the whole string", () => {
    // 0.2 * 1000 = 200, but the per-frame step is capped so a huge paste still types in.
    expect(nextRevealLength(0, 1000)).toBe(10);
  });

  it("advances at least one character on the final stretch", () => {
    expect(nextRevealLength(98, 100)).toBe(99);
    expect(nextRevealLength(99, 100)).toBe(100);
  });

  it("never overshoots the target", () => {
    expect(nextRevealLength(97, 100)).toBeLessThanOrEqual(100);
  });

  it("reveals the whole target in a finite, strictly increasing sequence", () => {
    const target = 250;
    let len = 0;
    for (let guard = 0; guard < 10_000 && len < target; guard++) {
      const next = nextRevealLength(len, target);
      expect(next).toBeGreaterThan(len);
      len = next;
    }
    expect(len).toBe(target);
  });
});
