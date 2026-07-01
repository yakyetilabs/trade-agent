import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SyntheticDataPill } from "./SyntheticDataPill";

describe("SyntheticDataPill", () => {
  it("states the load-bearing synthetic-data disclaimer", () => {
    render(<SyntheticDataPill />);
    expect(screen.getByText("Synthetic data")).toBeInTheDocument();
    // The explanatory tooltip is the load-bearing part - it must spell out that no real data exists.
    expect(screen.getByTitle(/synthetic.*no real trade data/i)).toBeInTheDocument();
  });
});
