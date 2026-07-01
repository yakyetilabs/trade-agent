import { useVendorScope } from "../vendor/VendorScopeContext";

function ChevronDown() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-fg-subtle"
    >
      <path d="m6 9 6 6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** The top-bar vendor scope selector, bound to the analyst's authorized vendors. */
export function VendorScopePicker() {
  const { vendors, loading, error, selectedVendorId, selectVendor } = useVendorScope();

  if (loading) {
    return <span className="text-xs text-fg-subtle">Loading vendors…</span>;
  }
  if (error) {
    return (
      <span className="text-xs text-danger" title={error}>
        Vendors unavailable
      </span>
    );
  }
  if (vendors.length === 0) {
    return <span className="text-xs text-fg-subtle">No vendors in scope</span>;
  }

  return (
    <div className="relative">
      <select
        aria-label="Vendor scope"
        value={selectedVendorId ?? ""}
        onChange={(event) => selectVendor(event.target.value)}
        className="max-w-[15rem] cursor-pointer appearance-none truncate rounded-lg border border-hairline bg-elevated py-1.5 pl-3 pr-8 font-mono text-xs text-fg transition-colors hover:border-fg-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50"
      >
        {vendors.map((vendor) => (
          <option key={vendor.vendor_id} value={vendor.vendor_id}>
            {vendor.vendor_id} · {vendor.legal_name}
          </option>
        ))}
      </select>
      <ChevronDown />
    </div>
  );
}
