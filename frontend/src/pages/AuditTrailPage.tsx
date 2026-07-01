/**
 * Audit Trail page. F1 renders the header + placeholder; F3 replaces the placeholder with the
 * recent-traces list (disposition filters) and the expandable per-trace tool-call timeline.
 */
export function AuditTrailPage() {
  return (
    <section>
      <header className="mb-6">
        <h1 className="text-xl font-semibold text-fg">Audit Trail</h1>
        <p className="mt-1 text-sm text-fg-muted">
          Every run, recorded: disposition, intent, latency, the billable token split, and the full
          tool-call timeline.
        </p>
      </header>

      <div className="rounded-xl border border-dashed border-hairline bg-surface/40 p-10 text-center">
        <p className="text-sm text-fg-muted">The recent-traces list and trace detail are coming next.</p>
      </div>
    </section>
  );
}
