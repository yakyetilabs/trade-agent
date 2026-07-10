import { describe, expect, it } from "vitest";

import { config } from "./config";

describe("config", () => {
  it("defaults the API base to same-origin /api", () => {
    // No VITE_API_BASE_URL in the test env, so the same-origin default applies.
    expect(config.apiBaseUrl).toBe("/api");
  });

  it("exposes the Vite mode", () => {
    expect(config.mode).toBe("test");
  });
});
