import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ReasoningPanel } from "./ReasoningPanel";

describe("ReasoningPanel", () => {
  it("renders the streamed reasoning, expanded by default", () => {
    render(<ReasoningPanel reasoning="Classifying the inquiry." streaming={false} />);
    expect(screen.getByText("Classifying the inquiry.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reasoning/i })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("collapses and re-expands the reasoning on toggle", async () => {
    const user = userEvent.setup();
    render(<ReasoningPanel reasoning="Hidden thought." streaming={false} />);
    const toggle = screen.getByRole("button", { name: /reasoning/i });

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Hidden thought.")).not.toBeInTheDocument();

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Hidden thought.")).toBeInTheDocument();
  });

  it("starts collapsed when defaultOpen is false (the audit-trail usage)", () => {
    render(<ReasoningPanel reasoning="Folded thought." streaming={false} defaultOpen={false} />);
    expect(screen.getByRole("button", { name: /reasoning/i })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.queryByText("Folded thought.")).not.toBeInTheDocument();
  });

  it("shows the thinking indicator and caret only while streaming", () => {
    const { rerender } = render(<ReasoningPanel reasoning="Working." streaming={true} />);
    expect(screen.getByText("Thinking")).toBeInTheDocument();
    expect(screen.getByTestId("streaming-caret")).toBeInTheDocument();

    rerender(<ReasoningPanel reasoning="Working." streaming={false} />);
    expect(screen.queryByText("Thinking")).not.toBeInTheDocument();
    expect(screen.queryByTestId("streaming-caret")).not.toBeInTheDocument();
  });
});
