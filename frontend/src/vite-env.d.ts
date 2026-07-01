/// <reference types="vite/client" />

// Typed frontend environment. These merge into Vite's ImportMetaEnv so `import.meta.env.VITE_*`
// is fully typed at the single read site (src/config.ts). Values are injected by Vite at build
// time from .env.local (see .env.local.example); they are public client identifiers, not secrets.
interface ImportMetaEnv {
  readonly VITE_FIREBASE_API_KEY: string;
  readonly VITE_FIREBASE_AUTH_DOMAIN: string;
  readonly VITE_FIREBASE_PROJECT_ID: string;
  readonly VITE_FIREBASE_APP_ID: string;
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

// @fontsource packages ship CSS with no type declarations; declare them so the side-effect imports
// in main.tsx satisfy `noUncheckedSideEffectImports`. Vite injects the CSS at build time.
declare module "@fontsource-variable/inter";
declare module "@fontsource-variable/jetbrains-mono";
