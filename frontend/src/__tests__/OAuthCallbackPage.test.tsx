import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import OAuthCallbackPage from '../pages/OAuthCallbackPage';

const renderAt = (path: string): void => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/oauth/callback" element={<OAuthCallbackPage />} />
          <Route path="/settings/accounts" element={<div data-testid="redirected">accounts</div>} />
          <Route path="/somewhere" element={<div data-testid="redirected">somewhere</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
};

describe('<OAuthCallbackPage>', () => {
  it('shows the success state and redirects to /settings/accounts after 800ms', async () => {
    renderAt('/oauth/callback');
    expect(screen.getByText(/account connected/i)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId('redirected')).toBeInTheDocument(), {
      timeout: 1500,
    });
  });

  it('honors the next= search param when redirecting', async () => {
    renderAt('/oauth/callback?status=ok&next=/somewhere');
    await waitFor(() => expect(screen.getByTestId('redirected')).toHaveTextContent('somewhere'), {
      timeout: 1500,
    });
  });

  it('renders the failure state when status is not ok', () => {
    renderAt('/oauth/callback?status=error&error=invalid_grant');
    expect(screen.getByText(/oauth failed/i)).toBeInTheDocument();
    expect(screen.getByText(/invalid_grant/)).toBeInTheDocument();
  });

  it('renders a default failure copy when error param is missing', () => {
    renderAt('/oauth/callback?status=error');
    expect(screen.getByText(/google did not complete the handshake/i)).toBeInTheDocument();
  });
});
