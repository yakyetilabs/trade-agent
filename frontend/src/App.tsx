import { BrowserRouter, Navigate, Route, Routes } from "react-router";

import { AppShell } from "./components/AppShell";
import { AuditTrailPage } from "./pages/AuditTrailPage";
import { ConsolePage } from "./pages/ConsolePage";

/**
 * App root and route table. The app is a public demo - no sign-in, every route renders
 * directly inside <AppShell>. Unknown paths fall back to the Console.
 */
export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<ConsolePage />} />
          <Route path="/traces" element={<AuditTrailPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
