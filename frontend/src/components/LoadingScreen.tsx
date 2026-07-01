import { Spinner } from "./Spinner";

/** Full-viewport centered loader for the auth `initializing` / `verifying` states. */
export function LoadingScreen({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-ink">
      <Spinner size={22} label={label} />
    </div>
  );
}
