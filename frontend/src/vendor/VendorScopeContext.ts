/**
 * Vendor-scope context shape + hook. The scope picker in the top bar writes here and the Console
 * (F2) reads the selected vendor from here. Split from the provider so this module exports no
 * components. Note: this selection is UX only - the backend re-authorizes the vendor on every call.
 */
import { createContext, useContext } from "react";
import type { Vendor } from "../types/api";

export interface VendorScopeValue {
  /** The analyst's authorized vendors (GET /api/vendors), or empty while loading / on error. */
  vendors: Vendor[];
  loading: boolean;
  error: string | null;
  selectedVendorId: string | null;
  /** The resolved selected vendor object, or null when none is selected. */
  selectedVendor: Vendor | null;
  selectVendor: (vendorId: string) => void;
  reload: () => void;
}

export const VendorScopeContext = createContext<VendorScopeValue | null>(null);

export function useVendorScope(): VendorScopeValue {
  const ctx = useContext(VendorScopeContext);
  if (ctx === null) {
    throw new Error("useVendorScope must be used within <VendorScopeProvider>.");
  }
  return ctx;
}
