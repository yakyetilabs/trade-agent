import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { THEME_STORAGE_KEY } from "../theme";
import { ThemeToggle } from "./ThemeToggle";

describe("ThemeToggle", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
  });

  afterEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
  });

  it("starts from the theme already stamped on <html> and offers the opposite", () => {
    document.documentElement.dataset.theme = "dark";
    render(<ThemeToggle />);
    // Dark active -> the control offers light.
    expect(screen.getByRole("button", { name: "Switch to light theme" })).toBeInTheDocument();
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("toggles the theme, stamps <html>, and persists the choice", async () => {
    const user = userEvent.setup();
    document.documentElement.dataset.theme = "dark";
    render(<ThemeToggle />);

    await user.click(screen.getByRole("button", { name: "Switch to light theme" }));

    expect(document.documentElement.dataset.theme).toBe("light");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
    // The control now offers the way back to dark.
    const back = screen.getByRole("button", { name: "Switch to dark theme" });

    await user.click(back);
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
  });
});
