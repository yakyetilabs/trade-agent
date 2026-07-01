// Registers @testing-library/jest-dom matchers (toBeInTheDocument, toHaveTextContent, ...) on
// Vitest's expect and augments its types. Loaded once via vite.config.ts `test.setupFiles`.
import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// We run with `globals: false`, so Testing Library's automatic afterEach cleanup is not registered
// for us. Unmount rendered trees between tests explicitly, else the DOM leaks across tests.
afterEach(() => {
  cleanup();
});
