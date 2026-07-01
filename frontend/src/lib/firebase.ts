/**
 * Firebase app + auth singletons and the ID-token provider.
 *
 * Firebase only AUTHENTICATES here - authorization is the backend's in-memory allowlist, so a
 * non-allowlisted Google account signs in fine but every /api call returns 403 (docs/PRODUCT.md).
 * Config comes from src/config.ts (the single env read). Auth is created lazily and cached: the
 * app can still boot and render a clear "not configured" notice when .env.local is missing, instead
 * of crashing at import.
 */
import { type FirebaseApp, initializeApp } from "firebase/app";
import { type Auth, GoogleAuthProvider, getAuth } from "firebase/auth";

import { config, isFirebaseConfigured } from "../config";

let cachedAuth: Auth | null = null;

/** The reusable Google sign-in provider (a plain config object - safe to build unconditionally). */
export const googleProvider = new GoogleAuthProvider();

/**
 * Lazily initialize (once) and return the Auth singleton. Throws a clear, actionable error if the
 * Firebase env config is incomplete - call sites guard with `isFirebaseConfigured()` first.
 */
export function getFirebaseAuth(): Auth {
  if (cachedAuth) return cachedAuth;
  if (!isFirebaseConfigured()) {
    throw new Error(
      "Firebase is not configured. Copy frontend/.env.local.example to frontend/.env.local and " +
        "fill the VITE_FIREBASE_* values from the Firebase console (project trade-agent-ff12a).",
    );
  }
  const app: FirebaseApp = initializeApp({
    apiKey: config.firebase.apiKey,
    authDomain: config.firebase.authDomain,
    projectId: config.firebase.projectId,
    // Only pass appId when present - it is optional for Auth (see config.ts).
    ...(config.firebase.appId ? { appId: config.firebase.appId } : {}),
  });
  cachedAuth = getAuth(app);
  return cachedAuth;
}

/**
 * Resolve the signed-in user's current Firebase ID token (the SDK auto-refreshes it on demand), or
 * null when signed out or unconfigured. This is the `TokenProvider` the API client uses to set the
 * `Authorization: Bearer` header on every request.
 */
export async function getFirebaseIdToken(): Promise<string | null> {
  if (!isFirebaseConfigured()) return null;
  const user = getFirebaseAuth().currentUser;
  return user ? user.getIdToken() : null;
}
