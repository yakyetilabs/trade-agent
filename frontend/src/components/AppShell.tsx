import { Outlet } from "react-router";

import { VendorScopeProvider } from "../vendor/VendorScopeProvider";
import { TopBar } from "./TopBar";

/**
 * The app layout: the persistent top bar over the routed page. Wrapped in
 * <VendorScopeProvider> so the vendor scope is loaded once and shared by the top-bar picker and
 * every page.
 */
export function AppShell() {
  return (
    <VendorScopeProvider>
      {/* Height-bounded to the viewport (h-dvh) with overflow contained here, so a page can pin a
          footer (the Console composer) while its own content region scrolls. Each routed page owns
          its scroll: the shell no longer body-scrolls, and `main` drops its vertical padding. */}
      <div className="flex h-dvh flex-col overflow-hidden bg-ink">
        <TopBar />
        <main className="mx-auto flex w-full min-h-0 max-w-7xl flex-1 flex-col px-4 sm:px-6">
          <Outlet />
        </main>
      </div>
    </VendorScopeProvider>
  );
}
