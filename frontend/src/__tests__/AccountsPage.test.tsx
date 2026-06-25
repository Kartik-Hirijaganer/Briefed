import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type * as ApiClient from '../api/client';
import { accounts } from '../api/queryKeys';
import AccountsPage from '../pages/settings/AccountsPage';

const apiMock = vi.hoisted(() => ({ GET: vi.fn() }));

vi.mock('../api/client', async (importOriginal) => {
  const actual = (await importOriginal()) as typeof ApiClient;
  return { ...actual, api: apiMock };
});

vi.mock('../hooks/useAddGmailFlow', () => ({
  useAddGmailFlow: () => ({ start: vi.fn(), startUrl: '/oauth/start', opensInNewTab: false }),
}));

vi.mock('../hooks/useBreakpoint', () => ({ useBreakpoint: () => 'lg' }));

vi.mock('../features/settings/AccountCard', () => ({
  AccountCard: ({ account }: { account: { id: string; email: string } }) => (
    <div data-testid={`account-${account.id}`}>{account.email}</div>
  ),
}));

vi.mock('../components/AppVersion', () => ({
  AppVersion: () => <span data-testid="app-version">v</span>,
}));

const renderPage = (client?: QueryClient): QueryClient => {
  const queryClient = client ?? new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AccountsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return queryClient;
};

describe('<AccountsPage>', () => {
  beforeEach(() => apiMock.GET.mockReset());

  it('renders one card per connected Gmail account', async () => {
    apiMock.GET.mockResolvedValue({
      data: {
        accounts: [
          { id: 'a1', email: 'one@example.com' },
          { id: 'a2', email: 'two@example.com' },
        ],
      },
    });
    renderPage();
    await waitFor(() => expect(screen.getByTestId('account-a1')).toBeInTheDocument());
    expect(screen.getByTestId('account-a2')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /add gmail account/i })).toBeInTheDocument();
  });

  it('refetches when a persisted accounts cache is already hydrated', async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: 5 * 60 * 1000 } },
    });
    client.setQueryData(accounts(), { accounts: [{ id: 'cached', email: 'cached@example.com' }] });
    apiMock.GET.mockResolvedValue({
      data: {
        accounts: [
          { id: 'primary', email: 'primary@example.com' },
          { id: 'secondary', email: 'secondary@example.com' },
        ],
      },
    });

    renderPage(client);

    await waitFor(() => expect(apiMock.GET).toHaveBeenCalledWith('/api/v1/accounts'));
    await waitFor(() => expect(screen.getByTestId('account-secondary')).toBeInTheDocument());
    expect(screen.queryByTestId('account-cached')).not.toBeInTheDocument();
  });

  it('renders the empty state when no accounts are connected', async () => {
    apiMock.GET.mockResolvedValue({ data: { accounts: [] } });
    renderPage();
    await waitFor(() => expect(screen.getByText(/no gmail accounts yet/i)).toBeInTheDocument());
  });

  it('renders the error state on a failed fetch', async () => {
    apiMock.GET.mockResolvedValue({ error: { detail: 'outage' }, response: { status: 500 } });
    renderPage();
    await waitFor(() => expect(screen.getByText(/could not load accounts/i)).toBeInTheDocument());
  });
});
