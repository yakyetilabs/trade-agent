import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DispositionFilter } from "./DispositionFilter";

const counts = { draft: 2, escalated: 1, approved: 3, rejected: 0 };

describe("DispositionFilter", () => {
  it("shows a count per bucket and marks the active tab", () => {
    render(<DispositionFilter value="all" counts={counts} total={6} onChange={vi.fn()} />);
    expect(screen.getByRole("tab", { name: "All, 6 traces" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("tab", { name: "Approved, 3 traces" })).toHaveAttribute(
      "aria-selected",
      "false",
    );
  });

  it("reports the chosen filter", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<DispositionFilter value="all" counts={counts} total={6} onChange={onChange} />);
    await user.click(screen.getByRole("tab", { name: "Draft, 2 traces" }));
    expect(onChange).toHaveBeenCalledWith("draft");
  });
});
