import { NavLink } from "react-router";

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
 *  pill, the vendor scope picker, and the theme toggle. */
export function TopBar() {
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
        </div>
      </div>
    </header>
  );
}
