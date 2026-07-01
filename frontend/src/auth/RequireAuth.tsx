import { Navigate, Outlet } from "react-router";

import { CenteredNotice } from "../components/CenteredNotice";
import { LoadingScreen } from "../components/LoadingScreen";
import { useAuth } from "./AuthContext";

/**
 * Route guard for the protected app. Renders the authorized routes via <Outlet> only in the
 * `authorized` state; every other lifecycle state resolves to a clear full-screen surface (loader,
 * redirect to sign-in, or a terminal notice). This is the single place authZ gates the UI - the
 * backend re-checks scope on every request regardless.
 */
export function RequireAuth() {
  const { status, email, error, signOut, retry } = useAuth();

  switch (status) {
    case "initializing":
      return <LoadingScreen label="Loading…" />;
    case "verifying":
      return <LoadingScreen label="Verifying access…" />;
    case "signed-out":
      return <Navigate to="/signin" replace />;
    case "misconfigured":
      return (
        <CenteredNotice
          tone="warn"
          title="Firebase is not configured"
          body="Set the VITE_FIREBASE_* values in frontend/.env.local (see .env.local.example), then reload the page."
        />
      );
    case "forbidden":
      return (
        <CenteredNotice
          tone="danger"
          title="Not authorized"
          body={`${email ?? "This account"} is signed in but is not on the analyst allowlist. Ask an administrator for access, or sign in with an approved account.`}
          action={{ label: "Sign out", onClick: () => void signOut() }}
        />
      );
    case "unavailable":
      return (
        <CenteredNotice
          tone="warn"
          title="Couldn’t verify access"
          body={error ?? "The backend could not be reached to verify authorization. Confirm it is running, then retry."}
          action={{ label: "Retry", onClick: retry }}
          secondaryAction={{ label: "Sign out", onClick: () => void signOut() }}
        />
      );
    case "authorized":
      return <Outlet />;
    default: {
      // Exhaustiveness guard: adding an AuthStatus without handling it here is a compile error.
      const unreachable: never = status;
      return unreachable;
    }
  }
}
