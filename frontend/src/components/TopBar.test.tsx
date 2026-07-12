import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { VendorScopeContext, type VendorScopeValue } from "../vendor/VendorScopeContext";
import type { Vendor } from "../types/api";
import { TopBar } from "./TopBar";

const VENDOR: Vendor = {
  vendor_id: "V-001",
  legal_name: "Meridian Components LLC",
  country: "Taiwan",
  customs_broker: "Pacific Rim Customs Brokerage",
  categories: ["electronics"],
  active: true,
};

const vendorValue: VendorScopeValue = {
  vendors: [VENDOR],
  loading: false,
  error: null,
  selectedVendorId: "V-001",
  selectedVendor: VENDOR,
  selectVendor: () => {},
  reload: () => {},
};

function renderTopBar() {
  return render(
    <MemoryRouter>
      <VendorScopeContext.Provider value={vendorValue}>
        <TopBar />
      </VendorScopeContext.Provider>
    </MemoryRouter>,
  );
}

describe("TopBar", () => {
  it("renders the shell chrome: brand, nav, and the synthetic pill", () => {
    renderTopBar();
    expect(screen.getByText("TradeOps AI")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Console" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Audit Trail" })).toHaveAttribute("href", "/traces");
    expect(screen.getByText("Synthetic data")).toBeInTheDocument();
    // Public demo: no identity or sign-out UI.
    expect(screen.queryByRole("button", { name: "Sign out" })).not.toBeInTheDocument();
  });

  it("binds the vendor scope picker to the vendors", () => {
    renderTopBar();
    const picker = screen.getByRole("combobox", { name: "Vendor scope" });
    expect(picker).toHaveValue("V-001");
    expect(screen.getByRole("option", { name: /Meridian Components LLC/ })).toBeInTheDocument();
  });
});
