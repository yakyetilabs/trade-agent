import { useCallback, useEffect, useState } from "react";

/** The two supported color themes. Dark (the "AgentOps" theme) is the default; light is a warm-ivory
 *  override of the neutral ramp only (src/index.css) - the accent and semantic hues are shared. */
export type Theme = "light" | "dark";

/** localStorage key holding the analyst's explicit choice (absent = follow the OS preference). */
export const THEME_STORAGE_KEY = "trade-agent-theme";

function isTheme(value: string | null | undefined): value is Theme {
  return value === "light" || value === "dark";
}

/**
 * Resolve the theme at first render: the value the pre-paint script in index.html already stamped on
 * `<html data-theme>`, else the stored choice, else the OS preference, else dark. Reading the stamped
 * attribute first keeps the hook in lockstep with what the user already sees - no flash, no mismatch.
 */
function resolveInitialTheme(): Theme {
  const stamped = document.documentElement.dataset.theme;
  if (isTheme(stamped)) return stamped;

  let stored: string | null = null;
  try {
    stored = localStorage.getItem(THEME_STORAGE_KEY);
  } catch {
    // localStorage unavailable (e.g. private mode) - fall through to the OS preference.
  }
  if (isTheme(stored)) return stored;

  return typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-color-scheme: light)").matches
    ? "light"
    : "dark";
}

export interface ThemeController {
  theme: Theme;
  toggle: () => void;
  setTheme: (theme: Theme) => void;
}

/**
 * Owns the active theme and keeps the DOM + localStorage in sync. Applying a theme stamps
 * `<html data-theme>`, which flips the neutral-ramp tokens (src/index.css) for every tokenized
 * utility; the `<html>` background is re-synced from the resolved token so an overscroll never
 * reveals the stale pre-paint color. One instance (the TopBar toggle) is the source of truth.
 */
export function useTheme(): ThemeController {
  const [theme, setThemeState] = useState<Theme>(resolveInitialTheme);

  useEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = theme;
    // Read the now-resolved token so the base color lives only in index.css, not duplicated here.
    const ink = getComputedStyle(root).getPropertyValue("--color-ink").trim();
    if (ink) root.style.backgroundColor = ink;
    try {
      localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch {
      // Persisting is best-effort; the in-memory theme still applies for this session.
    }
  }, [theme]);

  const setTheme = useCallback((next: Theme) => setThemeState(next), []);
  const toggle = useCallback(
    () => setThemeState((current) => (current === "light" ? "dark" : "light")),
    [],
  );

  return { theme, toggle, setTheme };
}
