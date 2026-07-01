import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

// Self-hosted variable fonts (loaded before index.css so the @font-face families resolve).
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "./index.css";

import { App } from "./App";

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Root element #root was not found in index.html.");
}

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
