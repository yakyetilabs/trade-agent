import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/api", () => ({ api: { setDisposition: vi.fn() } }));

import { api } from "../lib/api";
import { DispositionActions } from "./DispositionActions";

const setDisposition = vi.mocked(api.setDisposition);

afterEach(() => {
  vi.clearAllMocks();
});

describe("DispositionActions", () => {
  it("approves via the API and reports the recorded disposition", async () => {
    const user = userEvent.setup();
    setDisposition.mockResolvedValue({ trace_id: "tr-1", disposition: "approved" });
    const onDecided = vi.fn();
    render(<DispositionActions traceId="tr-1" onDecided={onDecided} />);

    await user.click(screen.getByRole("button", { name: "Approve & release" }));

    expect(setDisposition).toHaveBeenCalledWith("tr-1", "approved");
    await waitFor(() => expect(onDecided).toHaveBeenCalledWith("approved"));
  });

  it("surfaces an error and reports no decision on failure", async () => {
    const user = userEvent.setup();
    setDisposition.mockRejectedValue(new Error("Could not record."));
    const onDecided = vi.fn();
    render(<DispositionActions traceId="tr-1" onDecided={onDecided} />);

    await user.click(screen.getByRole("button", { name: "Reject" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not record.");
    expect(onDecided).not.toHaveBeenCalled();
  });
});
