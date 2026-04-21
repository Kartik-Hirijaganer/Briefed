import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { VitePWA } from 'vite-plugin-pwa';
import { defineConfig } from 'vitest/config';

const projectDir = fileURLToPath(new URL('.', import.meta.url));

/**
 * Vite config for the Briefed PWA.
 *
 * - Aliases `@briefed/ui` + `@briefed/contracts` to the workspace sources so
 *   no separate build step is required.
 * - Wires `vite-plugin-pwa` with the Phase 6 manifest. Runtime caching rules
 *   land in Phase 7; today we precache the app shell only.
 * - Proxies `/api` + `/oauth` to the local uvicorn during development so
 *   cookies and CSRF work against `http://localhost:5173` same-origin.
 */
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.svg'],
      manifest: {
        name: 'Briefed',
        short_name: 'Briefed',
        description: 'Personal AI email agent',
        display: 'standalone',
        theme_color: '#09090b',
        background_color: '#09090b',
        start_url: '/',
        scope: '/',
        icons: [
          { src: '/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icon-512.png', sizes: '512x512', type: 'image/png' },
          { src: '/icon-maskable.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
    }),
  ],
  resolve: {
    alias: {
      '@briefed/ui': resolve(projectDir, '../packages/ui/src/index.ts'),
      '@briefed/ui/tokens.css': resolve(projectDir, '../packages/ui/src/tokens.css'),
      '@briefed/contracts': resolve(projectDir, '../packages/contracts/src/index.ts'),
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false },
      '/oauth': { target: 'http://127.0.0.1:8000', changeOrigin: false },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.ts',
    css: true,
  },
});
