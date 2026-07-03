/**
 * Single frontend configuration source - the browser mirror of backend/src/config.py.
 *
 * import.meta.env is read exactly once, here, and re-exported as a typed, immutable object. No
 * other module reads import.meta.env (CLAUDE.md "Isolated Environment Context"). The Firebase
 * values are public client identifiers, not secrets - the backend allowlist is the real boundary.
 */

interface FirebaseConfig {
  readonly apiKey: string;
  readonly authDomain: string;
  readonly projectId: string;
  /** Optional - only needed for Analytics/installations, not for Auth. Empty when no Web App
   *  is registered; the Google sign-in popup works without it. */
  readonly appId: string;
}

interface AppConfig {
  readonly firebase: FirebaseConfig;
  /** API base URL. Dev: the same-origin "/api" default, which the Vite proxy forwards to the local
   *  backend. Prod: the split-origin api. subdomain, pinned via VITE_API_BASE_URL in
   *  .env.production - a cross-origin call to Cloud Run that the backend CORS-allowlists, kept
   *  DNS-only (no CDN) so the SSE reasoning stream arrives unbuffered. */
  readonly apiBaseUrl: string;
  /** Vite mode ("development" | "production" | "test"). */
  readonly mode: string;
}

const env = import.meta.env;

export const config: AppConfig = {
  firebase: {
    apiKey: env.VITE_FIREBASE_API_KEY ?? "",
    authDomain: env.VITE_FIREBASE_AUTH_DOMAIN ?? "",
    projectId: env.VITE_FIREBASE_PROJECT_ID ?? "",
    appId: env.VITE_FIREBASE_APP_ID ?? "",
  },
  apiBaseUrl: env.VITE_API_BASE_URL ?? "/api",
  mode: env.MODE,
};

/**
 * True only when every required Firebase field is present. `firebase.ts` asserts this before
 * initializing so a missing/incomplete `.env.local` fails with a clear, actionable message
 * instead of an opaque Firebase SDK error deep in the sign-in flow.
 */
export function isFirebaseConfigured(): boolean {
  // appId is intentionally excluded: Firebase Auth (the Google sign-in popup) needs only these
  // three, so a project without a registered Web App can still sign users in.
  const { apiKey, authDomain, projectId } = config.firebase;
  return Boolean(apiKey && authDomain && projectId);
}
