import '@briefed/ui/tokens.css';
import './index.css';

import { QueryClientProvider } from '@tanstack/react-query';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { RouterProvider } from 'react-router-dom';

import { queryClient } from './api/queryClient';
import { router } from './router';

const rootElement = document.getElementById('root');
if (!rootElement) throw new Error('Root element not found — index.html must include #root');

createRoot(rootElement).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
