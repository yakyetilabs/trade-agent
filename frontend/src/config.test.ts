import { describe, expect, it } from "vitest";

import { config, isFirebaseConfigured } from "./config";

describe("config", () => {
  it("defaults the API base to same-origin /api", () => {
    // No VITE_API_BASE_URL in the test env, so the same-origin default applies.
    expect(config.apiBaseUrl).toBe("/api");
  });

  it("exposes a fully-shaped firebase config object", () => {
    expect(config.firebase).toEqual({
      apiKey: expect.any(String),
      authDomain: expect.any(String),
      projectId: expect.any(String),
      appId: expect.any(String),
    });
  });

  it("reports firebase as not configured when credentials are absent", () => {
    // The test env supplies no VITE_FIREBASE_* values, so the guard must read them as missing.
    expect(isFirebaseConfigured()).toBe(false);
  });
});
