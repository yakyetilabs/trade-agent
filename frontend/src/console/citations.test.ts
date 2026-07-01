import { describe, expect, it } from "vitest";

import { tokenizeCitations } from "./citations";

describe("tokenizeCitations", () => {
  it("returns a single text token for text with no citations", () => {
    expect(tokenizeCitations("No identifiers here.")).toEqual([
      { kind: "text", value: "No identifiers here." },
    ]);
  });

  it("returns [] for empty input", () => {
    expect(tokenizeCitations("")).toEqual([]);
  });

  it("highlights a full HTS code and a shipment id, preserving surrounding text", () => {
    const tokens = tokenizeCitations("Shipment S-1003 falls under 8542.31.0001 today.");
    expect(tokens).toEqual([
      { kind: "text", value: "Shipment " },
      { kind: "shipment", value: "S-1003" },
      { kind: "text", value: " falls under " },
      { kind: "hts", value: "8542.31.0001" },
      { kind: "text", value: " today." },
    ]);
  });

  it("highlights an HTS heading (4.2) as well as a full code", () => {
    const tokens = tokenizeCitations("Heading 8542.31 covers it.");
    expect(tokens).toContainEqual({ kind: "hts", value: "8542.31" });
  });

  it("does not match a number embedded in a longer digit run", () => {
    const tokens = tokenizeCitations("Ref 12345.67 is not a code.");
    expect(tokens.every((t) => t.kind === "text")).toBe(true);
  });
});
