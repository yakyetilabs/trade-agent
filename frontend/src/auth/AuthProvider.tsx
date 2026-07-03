import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import { FirebaseError } from "firebase/app";
import {
  type User,
  onIdTokenChanged,
  signInWithPopup,
  signOut as firebaseSignOut,
} from "firebase/auth";

import { isFirebaseConfigured } from "../config";
import { api } from "../lib/api";
import { ApiError } from "../lib/apiClient";
import { getFirebaseAuth, googleProvider } from "../lib/firebase";
import { AuthContext, type AuthContextValue, type AuthStatus } from "./AuthContext";

/** The subset of state driven by Firebase + the authorization check (everything but the actions). */
interface CoreState {
  status: AuthStatus;
  user: User | null;
  email: string | null;
  error: string | null;
}

/** Map a Firebase sign-in failure to a user-facing message, or null when the user simply cancelled. */
function toSignInMessage(err: unknown): string | null {
  if (err instanceof FirebaseError) {
    switch (err.code) {
      case "auth/popup-closed-by-user":
      case "auth/cancelled-popup-request":
        return null; // The user dismissed the popup - not an error worth surfacing.
      case "auth/popup-blocked":
        return "Your browser blocked the sign-in popup. Allow popups for this site and try again.";
      case "auth/network-request-failed":
        return "Network error during sign-in. Check your connection and try again.";
      case "auth/unauthorized-domain":
        // Firebase rejects the OAuth flow before opening the popup when the serving origin isn't
        // allowlisted - the exact failure on a new custom domain. Name the fix so it's actionable.
        return (
          "This domain isn't authorized for sign-in. Add it under Firebase Authentication -> " +
          "Settings -> Authorized domains."
        );
      default:
        return "Sign-in failed. Please try again.";
    }
  }
  return "Sign-in failed. Please try again.";
}

/**
 * Owns the authentication + authorization lifecycle and exposes it via <AuthContext>. Firebase's
 * `onIdTokenChanged` drives sign-in/out; each signed-in user is checked once against the backend
 * allowlist (GET /api/me), distinguishing "not allowlisted" (403 -> forbidden) from "couldn't
 * check" (anything else -> unavailable, retryable). When Firebase is unconfigured the app still
 * renders, parked in `misconfigured`.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [core, setCore] = useState<CoreState>({
    status: isFirebaseConfigured() ? "initializing" : "misconfigured",
    user: null,
    email: null,
    error: null,
  });
  const [signInError, setSignInError] = useState<string | null>(null);

  const verify = useCallback(async (user: User) => {
    setCore({ status: "verifying", user, email: user.email, error: null });
    try {
      const identity = await api.getIdentity();
      setCore({ status: "authorized", user, email: identity.email, error: null });
    } catch (err) {
      if (err instanceof ApiError && err.isForbidden) {
        setCore({ status: "forbidden", user, email: user.email, error: null });
      } else {
        const message = err instanceof Error ? err.message : String(err);
        setCore({ status: "unavailable", user, email: user.email, error: message });
      }
    }
  }, []);

  useEffect(() => {
    if (!isFirebaseConfigured()) return;
    // onIdTokenChanged fires on sign-in, sign-out, and token refresh (a superset of
    // onAuthStateChanged), so the session stays in sync with Firebase's persisted state.
    return onIdTokenChanged(getFirebaseAuth(), (user) => {
      if (user) {
        void verify(user);
      } else {
        setCore({ status: "signed-out", user: null, email: null, error: null });
      }
    });
  }, [verify]);

  const signIn = useCallback(async () => {
    setSignInError(null);
    try {
      await signInWithPopup(getFirebaseAuth(), googleProvider);
      // The resulting state is driven by onIdTokenChanged above; nothing else to do here.
    } catch (err) {
      setSignInError(toSignInMessage(err));
    }
  }, []);

  const signOut = useCallback(async () => {
    setSignInError(null);
    if (isFirebaseConfigured()) {
      await firebaseSignOut(getFirebaseAuth());
    }
  }, []);

  const retry = useCallback(() => {
    const user = isFirebaseConfigured() ? getFirebaseAuth().currentUser : null;
    if (user) void verify(user);
  }, [verify]);

  const value = useMemo<AuthContextValue>(
    () => ({ ...core, signInError, signIn, signOut, retry }),
    [core, signInError, signIn, signOut, retry],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
