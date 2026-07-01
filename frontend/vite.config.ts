import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vitest/config";

// Same-origin dev wiring: the browser only ever calls `/api`, and Vite proxies that to the local
// backend. This mirrors the production Firebase Hosting `/api/**` rewrite, so CORS is off both
// paths (docs/DESIGN_DECISIONS.md §9). The backend runs locally on 127.0.0.1:8000 per CLAUDE.local.md.
const LOCAL_BACKEND = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      // `ws: false` + no buffering keeps the SSE stream (/api/inquiry/stream) flowing frame-by-frame.
      "/api": { target: LOCAL_BACKEND, changeOrigin: true },
    },
  },
  test: {
    environment: "jsdom",
    globals: false,
    setupFiles: ["./src/test/setup.ts"],
    restoreMocks: true,
    unstubGlobals: true,
    include: ["src/**/*.test.{ts,tsx}"],
    // Keep tests hermetic: never inherit a developer's real .env.local Firebase values, so the
    // config assertions (and any auth-dependent tests) behave identically on every machine.
    env: {
      VITE_FIREBASE_API_KEY: "",
      VITE_FIREBASE_AUTH_DOMAIN: "",
      VITE_FIREBASE_PROJECT_ID: "",
      VITE_FIREBASE_APP_ID: "",
    },
  },
});
