import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Vendor } from "../types/api";
import { ExamplePrompts } from "./ExamplePrompts";
import { buildExamplePrompts } from "./promptCatalog";

const ELECTRONICS_VENDOR: Vendor = {
  vendor_id: "V-001",
  legal_name: "Meridian Components LLC",
  country: "Taiwan",
  customs_broker: "Pacific Rim Customs Brokerage",
  categories: ["electronics"],
  active: true,
};

const TEXTILES_VENDOR: Vendor = {
  ...ELECTRONICS_VENDOR,
  vendor_id: "V-002",
  legal_name: "Cascade Textile Imports Inc.",
  categories: ["textiles"],
};

describe("ExamplePrompts", () => {
  it("renders the five-prompt tour when another vendor exists", () => {
    render(
      <ExamplePrompts
        vendor={ELECTRONICS_VENDOR}
        vendors={[ELECTRONICS_VENDOR, TEXTILES_VENDOR]}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByText("Try one of these")).toBeInTheDocument();
    expect(screen.getAllByRole("button")).toHaveLength(5);
  });

  it("grounds the tariff prompt in the selected vendor's category HTS code", () => {
    render(
      <ExamplePrompts
        vendor={ELECTRONICS_VENDOR}
        vendors={[ELECTRONICS_VENDOR, TEXTILES_VENDOR]}
        onSelect={vi.fn()}
      />,
    );
    // Electronics maps to the license-required microprocessor clause in the seed.
    expect(screen.getByText(/HTS 8542\.31\.0001/)).toBeInTheDocument();
  });

  it("names a DIFFERENT vendor's id in the scope-guard prompt", () => {
    render(
      <ExamplePrompts
        vendor={TEXTILES_VENDOR}
        vendors={[ELECTRONICS_VENDOR, TEXTILES_VENDOR]}
        onSelect={vi.fn()}
      />,
    );
    // Selected V-002: the scope chip must reference V-001 (the guard keys on V-### ids).
    expect(screen.getByText(/V-001 \(Meridian Components LLC\)/)).toBeInTheDocument();
  });

  it("omits the scope-guard prompt when no other vendor exists", () => {
    render(
      <ExamplePrompts
        vendor={ELECTRONICS_VENDOR}
        vendors={[ELECTRONICS_VENDOR]}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getAllByRole("button")).toHaveLength(4);
    expect(screen.queryByText("Scope guard")).not.toBeInTheDocument();
  });

  it("pre-fills via onSelect on click and never submits", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(
      <ExamplePrompts
        vendor={ELECTRONICS_VENDOR}
        vendors={[ELECTRONICS_VENDOR, TEXTILES_VENDOR]}
        onSelect={onSelect}
      />,
    );

    await user.click(screen.getByText(/under the table/));
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith(expect.stringContaining("under the table"));
  });

  it("keeps the escalation prompt phrased to match the deterministic guard", () => {
    const prompts = buildExamplePrompts(ELECTRONICS_VENDOR, [ELECTRONICS_VENDOR]);
    const escalation = prompts.find((p) => p.label === "Escalation guard");
    // The guard matches the spaced substring "under the table"; the chip must never
    // drift to a hyphenated form (a live-verified guard miss pre-normalization).
    expect(escalation?.prompt).toContain("under the table");
  });

  it("falls back to a generic tariff prompt for a category without a mapped code", () => {
    const prompts = buildExamplePrompts(
      { ...ELECTRONICS_VENDOR, categories: [] },
      [ELECTRONICS_VENDOR],
    );
    const tariff = prompts.find((p) => p.label === "Tariff & licensing");
    expect(tariff?.prompt).toBe("What tariff and licensing rules apply to my latest shipment's goods?");
  });
});
