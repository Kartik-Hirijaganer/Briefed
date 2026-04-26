/// <reference types="vite/client" />

/**
 * Compile-time global injected by `vite.config.ts` `define`. Reads from
 * `packages/contracts/version.json` so the bundle and the backend share
 * one source of truth for the app version (Track C — Phase I.8).
 */
declare const __APP_VERSION__: string;
