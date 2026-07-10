import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react";

import { api } from "../lib/api";
import type { Vendor } from "../types/api";
import { VendorScopeContext, type VendorScopeValue } from "./VendorScopeContext";

/**
 * Loads the vendor list once (GET /api/vendors) and holds the current selection.
 * The selection defaults to the first vendor and is preserved across reloads when possible.
 */
export function VendorScopeProvider({ children }: { children: ReactNode }) {
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedVendorId, setSelectedVendorId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await api.listVendors();
      setVendors(list);
      setSelectedVendorId((current) =>
        current && list.some((v) => v.vendor_id === current)
          ? current
          : (list[0]?.vendor_id ?? null),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setVendors([]);
      setSelectedVendorId(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const selectVendor = useCallback((vendorId: string) => {
    setSelectedVendorId(vendorId);
  }, []);

  const reload = useCallback(() => {
    void load();
  }, [load]);

  const value = useMemo<VendorScopeValue>(
    () => ({
      vendors,
      loading,
      error,
      selectedVendorId,
      selectedVendor: vendors.find((v) => v.vendor_id === selectedVendorId) ?? null,
      selectVendor,
      reload,
    }),
    [vendors, loading, error, selectedVendorId, selectVendor, reload],
  );

  return <VendorScopeContext.Provider value={value}>{children}</VendorScopeContext.Provider>;
}
