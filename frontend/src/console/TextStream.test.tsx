import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TextStream } from "./TextStream";

describe("TextStream", () => {
  it("renders the streamed model response", () => {
    render(<TextStream text="The shipment is held pending a license." streaming={false} />);
    expect(screen.getByText("The shipment is held pending a license.")).toBeInTheDocument();
  });

  it("shows the streaming caret only while streaming", () => {
    const { rerender } = render(<TextStream text="Drafting" streaming={true} />);
    expect(screen.getByTestId("streaming-caret")).toBeInTheDocument();

    rerender(<TextStream text="Drafting" streaming={false} />);
    expect(screen.queryByTestId("streaming-caret")).not.toBeInTheDocument();
  });
});
