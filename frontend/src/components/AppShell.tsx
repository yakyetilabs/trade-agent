import { Outlet } from "react-router";

import { VendorScopeProvider } from "../vendor/VendorScopeProvider";
import { TopBar } from "./TopBar";

/**
 * The authorized app layout: the persistent top bar over the routed page. Wrapped in
 * <VendorScopeProvider> so the vendor scope is loaded once and shared by the top-bar picker and
 * every page - and only ever fetched for an authorized analyst (this renders under RequireAuth).
 */
export function AppShell() {
  return (
    <VendorScopeProvider>
      <div className="flex min-h-screen flex-col bg-ink">
        <TopBar />
        <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-8 sm:px-6">
          <Outlet />
        </main>
      </div>
    </VendorScopeProvider>
  );
}
