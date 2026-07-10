import { NavLink } from "react-router";

import { useAuth } from "../auth/AuthContext";
import { AppLogo } from "./AppLogo";
import { SyntheticDataPill } from "./SyntheticDataPill";
import { ThemeToggle } from "./ThemeToggle";
import { VendorScopePicker } from "./VendorScopePicker";

function navLinkClass({ isActive }: { isActive: boolean }): string {
  const base = "rounded-md px-3 py-1.5 text-sm font-medium transition-colors";
  return isActive
    ? `${base} bg-elevated text-fg`
    : `${base} text-fg-muted hover:bg-elevated/60 hover:text-fg`;
}

/** The persistent shell top bar: brand, nav, and - pushed right - the load-bearing synthetic-data
 *  pill, the vendor scope picker, and the analyst identity + sign-out. */
export function TopBar() {
  const { email, signOut } = useAuth();

  return (
    <header className="z-20 shrink-0 border-b border-hairline bg-surface/80 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-7xl items-center gap-4 px-4 sm:px-6">
        <AppLogo />
        <nav className="ml-2 flex items-center gap-1">
          <NavLink to="/" end className={navLinkClass}>
            Console
          </NavLink>
          <NavLink to="/traces" className={navLinkClass}>
            Audit Trail
          </NavLink>
        </nav>

        <div className="ml-auto flex items-center gap-3 sm:gap-4">
          <SyntheticDataPill />
          <VendorScopePicker />
          <ThemeToggle />
          <div className="flex items-center gap-3 border-l border-hairline pl-3 sm:pl-4">
            {email ? (
              <span className="hidden max-w-[18ch] truncate text-xs text-fg-muted md:inline" title={email}>
                {email}
              </span>
            ) : null}
            <button
              type="button"
              onClick={() => void signOut()}
              className="rounded-md border border-hairline px-3 py-1.5 text-xs font-medium text-fg-muted transition-colors hover:bg-elevated hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50"
            >
              Sign out
            </button>
          </div>
        </div>
      </div>
    </header>
  );
}
