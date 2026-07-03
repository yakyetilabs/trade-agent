import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { PipelineView } from "./PipelineView";
import type { RunStages } from "./useInquiryRun";

/** A fully-completed run: every stage complete with its summary. */
function completeStages(): RunStages {
  return {
    classify: {
      status: "complete",
      summary: { intent: "manifest_flag_resolution", confidence: 0.92 },
    },
    lookup: { status: "complete", summary: { count: 2, shipment_ids: ["S-1001", "S-1002"] } },
    retrieve: { status: "complete", summary: { hts_codes: ["8542.31.0001"], exact_hit: true } },
    draft: { status: "complete", summary: { ready: true } },
  };
}

/** A guarded run: the model never ran, so every stage is skipped. */
function skippedStages(): RunStages {
  return {
    classify: { status: "skipped", summary: null },
    lookup: { status: "skipped", summary: null },
    retrieve: { status: "skipped", summary: null },
    draft: { status: "skipped", summary: null },
  };
}

describe("PipelineView", () => {
  it("renders the full four-stage card while a run streams (not collapsed)", () => {
    render(<PipelineView stages={completeStages()} guard={null} />);

    expect(screen.getByRole("heading", { name: /pipeline/i })).toBeInTheDocument();
    for (const label of ["Classify", "Look up", "Retrieve", "Draft"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    // The live view has no disclosure toggle - the stages are always shown.
    expect(screen.queryByRole("button", { name: /pipeline/i })).not.toBeInTheDocument();
  });

  it("condenses to a click-to-expand summary once the run settles", async () => {
    const user = userEvent.setup();
    render(<PipelineView stages={completeStages()} guard={null} collapsed />);

    const toggle = screen.getByRole("button", { name: /pipeline/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    // The one-line result summary shows; the full per-stage detail is folded away.
    expect(screen.getByText(/Manifest flag resolution/)).toBeInTheDocument();
    expect(screen.queryByText("Retrieve")).not.toBeInTheDocument();

    await user.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Retrieve")).toBeInTheDocument();
  });

  it("keeps the guard banner visible while collapsed", () => {
    render(
      <PipelineView stages={skippedStages()} guard={{ kind: "escalation", reason: "sanctions" }} collapsed />,
    );

    expect(screen.getByText(/Routed to a human reviewer/)).toBeInTheDocument();
    // The banner is not hidden behind the disclosure; the stages stay folded.
    expect(screen.queryByText("Retrieve")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /pipeline/i })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });
});
