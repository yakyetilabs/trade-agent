import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { InquiryForm } from "./InquiryForm";

/** Test harness owning the controlled value, mirroring ConsolePage's wiring. */
function ControlledInquiryForm({
  vendorId = "V-001",
  running = false,
  initialValue = "",
  onSubmit = vi.fn(),
  isTerminal = false,
  onReset = vi.fn(),
}: {
  vendorId?: string | null;
  running?: boolean;
  initialValue?: string;
  onSubmit?: (inquiry: string) => void;
  isTerminal?: boolean;
  onReset?: () => void;
}) {
  const [value, setValue] = useState(initialValue);
  return (
    <InquiryForm
      vendorId={vendorId}
      running={running}
      value={value}
      onChange={setValue}
      onSubmit={onSubmit}
      isTerminal={isTerminal}
      onReset={onReset}
    />
  );
}

describe("InquiryForm", () => {
  it("blocks submission until a vendor is selected", () => {
    render(<ControlledInquiryForm vendorId={null} />);
    expect(screen.getByRole("button", { name: "Run inquiry" })).toBeDisabled();
    expect(screen.getByText("Select a vendor to run an inquiry.")).toBeInTheDocument();
  });

  it("enables submission with a vendor + text and submits the trimmed inquiry", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<ControlledInquiryForm onSubmit={onSubmit} />);

    await user.type(screen.getByLabelText("Inquiry"), "  why held?  ");
    const button = screen.getByRole("button", { name: "Run inquiry" });
    expect(button).toBeEnabled();

    await user.click(button);
    expect(onSubmit).toHaveBeenCalledWith("why held?");
  });

  it("locks the input and relabels the button while a run is in flight", () => {
    render(<ControlledInquiryForm running={true} />);
    expect(screen.getByRole("button", { name: "Running…" })).toBeDisabled();
    expect(screen.getByLabelText("Inquiry")).toBeDisabled();
  });

  it("renders an externally pre-filled value (the example-prompt path)", () => {
    render(<ControlledInquiryForm initialValue="What is the status of shipment S-9999?" />);
    expect(screen.getByLabelText("Inquiry")).toHaveValue(
      "What is the status of shipment S-9999?",
    );
    expect(screen.getByRole("button", { name: "Run inquiry" })).toBeEnabled();
  });

  it("reveals the New inquiry reset only once a run has settled, and calls onReset", async () => {
    const user = userEvent.setup();
    const onReset = vi.fn();
    const { rerender } = render(
      <ControlledInquiryForm isTerminal={false} onReset={onReset} />,
    );
    expect(screen.queryByRole("button", { name: "New inquiry" })).not.toBeInTheDocument();

    rerender(<ControlledInquiryForm isTerminal={true} onReset={onReset} />);
    await user.click(screen.getByRole("button", { name: "New inquiry" }));
    expect(onReset).toHaveBeenCalledTimes(1);
  });
});
