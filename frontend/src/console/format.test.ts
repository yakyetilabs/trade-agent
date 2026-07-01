import { describe, expect, it } from "vitest";

import { formatConfidence, formatLatency, formatTokens, humanizeIntent } from "./format";

describe("humanizeIntent", () => {
  it("title-cases and de-underscores an intent", () => {
    expect(humanizeIntent("manifest_flag_resolution")).toBe("Manifest flag resolution");
  });
  it("falls back to Unknown for null/undefined", () => {
    expect(humanizeIntent(null)).toBe("Unknown");
    expect(humanizeIntent(undefined)).toBe("Unknown");
  });
});

describe("formatConfidence", () => {
  it("renders a fraction as a whole percent", () => {
    expect(formatConfidence(0.92)).toBe("92%");
  });
  it("renders - when absent", () => {
    expect(formatConfidence(null)).toBe("-");
  });
});

describe("formatLatency", () => {
  it("uses ms under a second and s at or above", () => {
    expect(formatLatency(440)).toBe("440 ms");
    expect(formatLatency(1234)).toBe("1.2 s");
  });
  it("renders - when absent", () => {
    expect(formatLatency(null)).toBe("-");
  });
});

describe("formatTokens", () => {
  it("groups thousands and renders - when absent", () => {
    expect(formatTokens(12282)).toBe("12,282");
    expect(formatTokens(null)).toBe("-");
    expect(formatTokens(0)).toBe("0");
  });
});
