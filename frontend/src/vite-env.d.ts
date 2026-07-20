/// <reference types="vite/client" />

// Typed frontend environment. This merges into Vite's ImportMetaEnv so `import.meta.env.VITE_*`
// is fully typed at the single read site (src/config.ts). Optional because only the production
// build pins it (.env.production); dev leaves it unset and falls back to the same-origin proxy.
interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

// @fontsource packages ship CSS with no type declarations; declare them so the side-effect imports
// in main.tsx satisfy `noUncheckedSideEffectImports`. Vite injects the CSS at build time.
declare module "@fontsource-variable/inter";
declare module "@fontsource-variable/jetbrains-mono";
