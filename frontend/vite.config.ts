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
 * - Wires `vite-plugin-pwa` with Phase 7 runtime caching for digest,
 *   summary, jobs, news, unsubscribe, and history reads.
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
      workbox: {
        cleanupOutdatedCaches: true,
        navigateFallback: '/index.html',
        globPatterns: ['**/*.{js,css,html,svg,png,ico,webmanifest}'],
        runtimeCaching: [
          {
            urlPattern: ({ request, url }) =>
              request.method === 'GET' && url.pathname.startsWith('/api/v1/digest'),
            handler: 'StaleWhileRevalidate',
            options: {
              cacheName: 'briefed-digests',
              expiration: { maxEntries: 100, maxAgeSeconds: 7 * 24 * 60 * 60 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
          {
            urlPattern: ({ request, url }) =>
              request.method === 'GET' &&
              [
                '/api/v1/emails',
                '/api/v1/jobs',
                '/api/v1/news',
                '/api/v1/unsubscribes',
                '/api/v1/history',
              ].some((path) => url.pathname.startsWith(path)),
            handler: 'StaleWhileRevalidate',
            options: {
              cacheName: 'briefed-dashboard-reads',
              expiration: { maxEntries: 100, maxAgeSeconds: 7 * 24 * 60 * 60 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
          {
            urlPattern: ({ request, url }) =>
              request.method === 'GET' &&
              url.pathname.startsWith('/api/v1/summaries/'),
            handler: 'CacheFirst',
            options: {
              cacheName: 'briefed-summary-reads',
              expiration: { maxEntries: 300, maxAgeSeconds: 30 * 24 * 60 * 60 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
        ],
      },
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
    alias: [
      {
        find: '@briefed/ui/tokens.css',
        replacement: resolve(projectDir, '../packages/ui/src/tokens.css'),
      },
      { find: '@briefed/ui', replacement: resolve(projectDir, '../packages/ui/src/index.ts') },
      {
        find: '@briefed/contracts',
        replacement: resolve(projectDir, '../packages/contracts/src/index.ts'),
      },
    ],
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
