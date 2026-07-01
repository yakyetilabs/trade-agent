/**
 * Auth context shape + hook. Kept separate from <AuthProvider> so this module exports no components
 * (clean react-refresh boundary) and so any module can import the hook without pulling the provider.
 */
import { createContext, useContext } from "react";
import type { User } from "firebase/auth";

/**
 * The authentication + authorization lifecycle. Firebase governs authN (`signed-out` -> a `User`);
 * the backend allowlist governs authZ, checked once via GET /api/me:
 * - `initializing`  - waiting for Firebase's first token callback.
 * - `misconfigured` - no VITE_FIREBASE_* env; the app can render but cannot sign anyone in.
 * - `signed-out`    - no Firebase user.
 * - `verifying`     - a user is present; confirming they are on the allowlist.
 * - `authorized`    - allowlisted (200 from /api/me); the app is usable.
 * - `forbidden`     - authenticated but not allowlisted (403); a clear dead-end.
 * - `unavailable`   - the check failed for another reason (e.g. backend down); retryable.
 */
export type AuthStatus =
  | "initializing"
  | "misconfigured"
  | "signed-out"
  | "verifying"
  | "authorized"
  | "forbidden"
  | "unavailable";

export interface AuthContextValue {
  status: AuthStatus;
  user: User | null;
  /** The verified analyst email once authorized; otherwise the Firebase user's email if known. */
  email: string | null;
  /** Message for the `unavailable` state (why the authorization check could not complete). */
  error: string | null;
  /** Message for a failed sign-in attempt, or null (null also covers a user-cancelled popup). */
  signInError: string | null;
  signIn: () => Promise<void>;
  signOut: () => Promise<void>;
  /** Re-run the authorization check - backs the "retry" affordance on the `unavailable` screen. */
  retry: () => void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (ctx === null) {
    throw new Error("useAuth must be used within <AuthProvider>.");
  }
  return ctx;
}
