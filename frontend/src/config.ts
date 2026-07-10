/**
 * Single frontend configuration source - the browser mirror of backend/src/config.py.
 *
 * import.meta.env is read exactly once, here, and re-exported as a typed, immutable object. No
 * other module reads import.meta.env (CLAUDE.md "Isolated Environment Context").
 */

interface AppConfig {
  /** API base URL. Dev: the same-origin "/api" default, which the Vite proxy forwards to the local
   *  backend. Prod: the split-origin api. subdomain, pinned via VITE_API_BASE_URL in
   *  .env.production - a cross-origin call to Cloud Run that the backend CORS-allowlists, kept
   *  DNS-only (no CDN) so the SSE reasoning stream arrives unbuffered. */
  readonly apiBaseUrl: string;
  /** Vite mode ("development" | "production" | "test"). */
  readonly mode: string;
}

// Per-key reads so Vite inlines only these values into the bundle - capturing the whole
// import.meta.env object would embed every VITE_* var the machine's .env.local happens to hold.
export const config: AppConfig = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL ?? "/api",
  mode: import.meta.env.MODE,
};
