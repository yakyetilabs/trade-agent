import { BrowserRouter, Navigate, Route, Routes } from "react-router";

import { AuthProvider } from "./auth/AuthProvider";
import { RequireAuth } from "./auth/RequireAuth";
import { AppShell } from "./components/AppShell";
import { AuditTrailPage } from "./pages/AuditTrailPage";
import { ConsolePage } from "./pages/ConsolePage";
import { SignInPage } from "./pages/SignInPage";

/**
 * App root and route table. /signin is public; everything else is gated by <RequireAuth> and framed
 * by <AppShell>. <AuthProvider> wraps the router so the guard and the sign-in screen share one
 * source of auth truth. Unknown paths fall back to the Console.
 */
export function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/signin" element={<SignInPage />} />
          <Route element={<RequireAuth />}>
            <Route element={<AppShell />}>
              <Route path="/" element={<ConsolePage />} />
              <Route path="/traces" element={<AuditTrailPage />} />
            </Route>
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
