import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { InquiryForm } from "./InquiryForm";

describe("InquiryForm", () => {
  it("blocks submission until a vendor is selected", () => {
    render(<InquiryForm vendorId={null} running={false} onSubmit={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Run inquiry" })).toBeDisabled();
    expect(screen.getByText("Select a vendor to run an inquiry.")).toBeInTheDocument();
  });

  it("enables submission with a vendor + text and submits the trimmed inquiry", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<InquiryForm vendorId="V-001" running={false} onSubmit={onSubmit} />);

    await user.type(screen.getByLabelText("Inquiry"), "  why held?  ");
    const button = screen.getByRole("button", { name: "Run inquiry" });
    expect(button).toBeEnabled();

    await user.click(button);
    expect(onSubmit).toHaveBeenCalledWith("why held?");
  });

  it("locks the input and relabels the button while a run is in flight", () => {
    render(<InquiryForm vendorId="V-001" running={true} onSubmit={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Running…" })).toBeDisabled();
    expect(screen.getByLabelText("Inquiry")).toBeDisabled();
  });
});
