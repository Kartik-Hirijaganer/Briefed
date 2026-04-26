/**
 * Sentry SDK bootstrap for the React PWA (plan §14 Phase 8).
 *
 * The DSN is sourced from `import.meta.env.VITE_SENTRY_DSN`. When unset
 * (the dev + test default) initialization is a no-op so unit tests do
 * not need to stub the network. The browser SDK is imported lazily so
 * the cold-bundle size stays roughly the same for users who run the
 * dev build.
 */

import * as Sentry from '@sentry/react';

let initialized = false;

/**
 * Initialize Sentry browser tracing + error reporting.
 *
 * @returns The Sentry SDK reference for callers that want to attach
 *          breadcrumbs (`Sentry.addBreadcrumb`) or scopes.
 */
export function initSentry(): typeof Sentry {
  if (initialized) return Sentry;
  const dsn = import.meta.env.VITE_SENTRY_DSN;
  if (!dsn) {
    initialized = true;
    return Sentry;
  }
  Sentry.init({
    dsn,
    environment: import.meta.env.VITE_BRIEFED_ENV ?? 'local',
    tracesSampleRate: 0.05,
    replaysSessionSampleRate: 0,
    replaysOnErrorSampleRate: 0,
    sendDefaultPii: false,
  });
  initialized = true;
  return Sentry;
}

export { Sentry };
