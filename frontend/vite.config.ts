import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vitest/config";

// Same-origin dev wiring: the browser only ever calls `/api`, and Vite proxies that to the local
// backend, so CORS stays off the dev path. Production is split-origin instead - the SPA calls the
// `api.` subdomain cross-origin and the backend allowlists it in CORS middleware
// (docs/DESIGN_DECISIONS.md §9). The backend runs locally on 127.0.0.1:8000 per CLAUDE.local.md.
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
  },
});
