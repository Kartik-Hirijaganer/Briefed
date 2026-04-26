import '@briefed/ui/tokens.css';
import './index.css';

import { PersistQueryClientProvider } from '@tanstack/react-query-persist-client';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { RouterProvider } from 'react-router-dom';

import { queryClient } from './api/queryClient';
import { initSentry, Sentry } from './observability/sentry';
import { queryPersister } from './offline/queryPersistence';
import { router } from './router';

// Sentry must initialize before anything else so unhandled exceptions in
// React render or the router boot path are captured. Plan §14 Phase 8.
initSentry();

const rootElement = document.getElementById('root');
if (!rootElement) throw new Error('Root element not found — index.html must include #root');

createRoot(rootElement).render(
  <StrictMode>
    <Sentry.ErrorBoundary
      fallback={
        <div role="alert" style={{ padding: '2rem', textAlign: 'center' }}>
          Something went wrong. Please refresh the page.
        </div>
      }
    >
      <PersistQueryClientProvider
        client={queryClient}
        persistOptions={{
          persister: queryPersister,
          maxAge: 7 * 24 * 60 * 60 * 1000,
          buster: 'briefed-pwa-cache-v1',
          dehydrateOptions: {
            shouldDehydrateQuery: (query) => query.state.status === 'success',
          },
        }}
      >
        <RouterProvider router={router} />
      </PersistQueryClientProvider>
    </Sentry.ErrorBoundary>
  </StrictMode>,
);
