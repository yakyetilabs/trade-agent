import { useVendorScope } from "../vendor/VendorScopeContext";

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-fg-subtle">{label}</dt>
      <dd className="mt-0.5 text-fg">{value}</dd>
    </div>
  );
}

/**
 * Console page. F1 renders the scoped vendor context and a placeholder; F2 replaces the placeholder
 * with the inquiry input, the live four-stage SSE pipeline, the grounded draft, and the actions.
 */
export function ConsolePage() {
  const { selectedVendor } = useVendorScope();

  return (
    <section>
      <header className="mb-6">
        <h1 className="text-xl font-semibold text-fg">Console</h1>
        <p className="mt-1 text-sm text-fg-muted">
          Submit an inquiry, watch the agent pipeline run, then review and release the grounded
          draft.
        </p>
      </header>

      {selectedVendor ? (
        <div className="mb-6 rounded-xl border border-hairline bg-surface p-5">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="font-mono text-sm text-accent">{selectedVendor.vendor_id}</span>
            <span className="text-sm font-medium text-fg">{selectedVendor.legal_name}</span>
          </div>
          <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 text-xs sm:grid-cols-3">
            <Field label="Country" value={selectedVendor.country} />
            <Field label="Customs broker" value={selectedVendor.customs_broker} />
            <Field label="Categories" value={selectedVendor.categories.join(", ")} />
          </dl>
        </div>
      ) : null}

      <div className="rounded-xl border border-dashed border-hairline bg-surface/40 p-10 text-center">
        <p className="text-sm text-fg-muted">
          The inquiry input and the live four-stage pipeline are coming next.
        </p>
        <p className="mt-1 text-xs text-fg-subtle">
          Foundation ready: auth, the API client, vendor scope, and the streaming contract are wired.
        </p>
      </div>
    </section>
  );
}
