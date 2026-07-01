import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { AuthContext, type AuthContextValue } from "../auth/AuthContext";
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

const authValue: AuthContextValue = {
  status: "authorized",
  user: null,
  email: "analyst@example.com",
  error: null,
  signInError: null,
  signIn: async () => {},
  signOut: async () => {},
  retry: () => {},
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
      <AuthContext.Provider value={authValue}>
        <VendorScopeContext.Provider value={vendorValue}>
          <TopBar />
        </VendorScopeContext.Provider>
      </AuthContext.Provider>
    </MemoryRouter>,
  );
}

describe("TopBar", () => {
  it("renders the shell chrome: brand, nav, synthetic pill, identity, and sign-out", () => {
    renderTopBar();
    expect(screen.getByText("trade-agent")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Console" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Audit Trail" })).toHaveAttribute("href", "/traces");
    expect(screen.getByText("Synthetic data")).toBeInTheDocument();
    expect(screen.getByText("analyst@example.com")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });

  it("binds the vendor scope picker to the authorized vendors", () => {
    renderTopBar();
    const picker = screen.getByRole("combobox", { name: "Vendor scope" });
    expect(picker).toHaveValue("V-001");
    expect(screen.getByRole("option", { name: /Meridian Components LLC/ })).toBeInTheDocument();
  });
});
