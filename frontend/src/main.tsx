import '@briefed/ui/tokens.css';
import './index.css';

import { PersistQueryClientProvider } from '@tanstack/react-query-persist-client';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { RouterProvider } from 'react-router-dom';

import { queryClient } from './api/queryClient';
import { queryPersister } from './offline/queryPersistence';
import { router } from './router';

const rootElement = document.getElementById('root');
if (!rootElement) throw new Error('Root element not found — index.html must include #root');

createRoot(rootElement).render(
  <StrictMode>
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
  </StrictMode>,
);
