import { Navigate } from "react-router";

import { useAuth } from "../auth/AuthContext";
import { AppLogo } from "../components/AppLogo";
import { SyntheticDataPill } from "../components/SyntheticDataPill";

/** The multi-color Google "G" for the one-click sign-in button. */
function GoogleGlyph() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
      <path
        fill="#EA4335"
        d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
      />
      <path
        fill="#4285F4"
        d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
      />
      <path
        fill="#FBBC05"
        d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
      />
      <path
        fill="#34A853"
        d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
      />
    </svg>
  );
}

/**
 * The sign-in surface: one-click Google, the brand moment, and the plainly-stated synthetic-data
 * disclaimer. Firebase authenticates; the backend allowlist authorizes, so a non-allowlisted Google
 * account lands on the "not authorized" state after sign-in rather than being rejected here.
 */
export function SignInPage() {
  const { status, signIn, signInError } = useAuth();

  // An already-authorized analyst never needs this screen.
  if (status === "authorized") {
    return <Navigate to="/" replace />;
  }

  const misconfigured = status === "misconfigured";
  const busy = status === "initializing" || status === "verifying";

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-ink px-6">
      {/* A single soft accent glow - the one place the brand color carries the empty space. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute left-1/2 top-[-10%] h-[420px] w-[720px] -translate-x-1/2 rounded-full bg-accent/12 blur-[120px]"
      />

      <div className="relative w-full max-w-md rounded-2xl border border-hairline bg-surface/90 p-8 shadow-2xl shadow-black/50">
        <AppLogo />

        <h1 className="mt-8 text-2xl font-semibold tracking-tight text-fg">Sign in</h1>
        <p className="mt-2 text-sm leading-relaxed text-fg-muted">
          AI-assisted triage for held and flagged US import shipments. Sign in with an approved
          analyst account to open the console.
        </p>

        <button
          type="button"
          onClick={() => void signIn()}
          disabled={misconfigured || busy}
          className="mt-7 flex w-full items-center justify-center gap-3 rounded-lg border border-hairline bg-elevated px-4 py-2.5 text-sm font-medium text-fg transition-colors hover:bg-elevated/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:ring-offset-2 focus-visible:ring-offset-ink disabled:cursor-not-allowed disabled:opacity-50"
        >
          <GoogleGlyph />
          Continue with Google
        </button>

        {signInError ? (
          <p className="mt-3 text-sm text-danger" role="alert">
            {signInError}
          </p>
        ) : null}
        {misconfigured ? (
          <p className="mt-3 text-sm text-warn" role="alert">
            Firebase is not configured. Set the VITE_FIREBASE_* values in frontend/.env.local and
            reload.
          </p>
        ) : null}

        <div className="mt-8 flex items-start gap-3 border-t border-hairline pt-6">
          <SyntheticDataPill />
          <p className="text-xs leading-relaxed text-fg-subtle">
            Demonstration only. All vendors, shipments, and tariff clauses are synthetic - no real
            trade data is present, and no filing is ever submitted.
          </p>
        </div>
      </div>
    </div>
  );
}
