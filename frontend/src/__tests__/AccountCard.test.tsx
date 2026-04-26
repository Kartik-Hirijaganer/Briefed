import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type * as ApiClient from '../api/client';
import { AccountCard } from '../features/settings/AccountCard';

const apiMock = vi.hoisted(() => ({ PATCH: vi.fn(), DELETE: vi.fn() }));
const startReconnect = vi.hoisted(() => vi.fn());
const breakpointMock = vi.hoisted(() => ({ value: 'lg' as 'sm' | 'md' | 'lg' }));

vi.mock('../api/client', async (importOriginal) => {
  const actual = (await importOriginal()) as typeof ApiClient;
  return { ...actual, api: apiMock };
});
vi.mock('../hooks/useAddGmailFlow', () => ({
  useAddGmailFlow: () => ({ start: startReconnect, startUrl: '/oauth', opensInNewTab: false }),
}));
vi.mock('../hooks/useBreakpoint', () => ({ useBreakpoint: () => breakpointMock.value }));
vi.mock('../hooks/useOnlineStatus', () => ({ useOnlineStatus: () => true }));
vi.mock('../offline/mutations', () => ({ enqueueMutation: vi.fn() }));

const account = {
  id: 'a1',
  email: 'me@example.com',
  display_name: 'Personal',
  status: 'active' as const,
  auto_scan_enabled: true,
  exclude_from_global_digest: false,
  emails_ingested_24h: 12,
  daily_budget_used_pct: 35.7,
  created_at: '2025-01-01T00:00:00Z',
  last_sync_at: '2026-04-25T10:00:00Z',
};

const renderCard = (overrides: Partial<typeof account> = {}): { client: QueryClient } => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AccountCard account={{ ...account, ...overrides }} />
    </QueryClientProvider>,
  );
  return { client };
};

describe('<AccountCard>', () => {
  beforeEach(() => {
    apiMock.PATCH.mockReset();
    apiMock.DELETE.mockReset();
    startReconnect.mockReset();
    breakpointMock.value = 'lg';
  });

  it('renders the display name, status badge, last-sync line, and counts', () => {
    renderCard();
    expect(screen.getByText('Personal')).toBeInTheDocument();
    expect(screen.getByText('Active')).toBeInTheDocument();
    expect(screen.getByText(/12 emails in last 24 h/)).toBeInTheDocument();
    expect(screen.getByText(/36% of daily budget/)).toBeInTheDocument();
  });

  it('PATCHes the auto-scan toggle', async () => {
    apiMock.PATCH.mockResolvedValue({ data: { ...account, auto_scan_enabled: false } });
    const user = userEvent.setup();
    renderCard();
    await user.click(screen.getByRole('switch', { name: /toggle auto-scan/i }));
    await waitFor(() => expect(apiMock.PATCH).toHaveBeenCalled());
    expect(apiMock.PATCH).toHaveBeenCalledWith('/api/v1/accounts/{account_id}', {
      params: { path: { account_id: 'a1' } },
      body: { auto_scan_enabled: false },
    });
  });

  it('opens the More sheet and toggles exclude-from-global', async () => {
    apiMock.PATCH.mockResolvedValue({ data: { ...account, exclude_from_global_digest: true } });
    const user = userEvent.setup();
    renderCard();
    await user.click(screen.getByRole('button', { name: /more actions/i }));
    await user.click(screen.getByRole('button', { name: /exclude from global digest/i }));
    await waitFor(() => expect(apiMock.PATCH).toHaveBeenCalled());
    expect(apiMock.PATCH).toHaveBeenCalledWith('/api/v1/accounts/{account_id}', {
      params: { path: { account_id: 'a1' } },
      body: { exclude_from_global_digest: true },
    });
  });

  it('opens the disconnect dialog and DELETEs on confirm', async () => {
    apiMock.DELETE.mockResolvedValue({ data: undefined });
    const user = userEvent.setup();
    renderCard();
    await user.click(screen.getByRole('button', { name: /^disconnect me@example.com$/i }));
    expect(screen.getByText(/Disconnect me@example.com\?/)).toBeInTheDocument();
    const dialogConfirm = screen.getAllByRole('button', { name: /^disconnect$/i })[0]!;
    await user.click(dialogConfirm);
    await waitFor(() => expect(apiMock.DELETE).toHaveBeenCalled());
    expect(apiMock.DELETE).toHaveBeenCalledWith('/api/v1/accounts/{account_id}', {
      params: { path: { account_id: 'a1' } },
    });
  });

  it('reconnect entry triggers the OAuth flow start', async () => {
    const user = userEvent.setup();
    renderCard({ status: 'needs_reauth' });
    await user.click(screen.getByRole('button', { name: /more actions/i }));
    await user.click(screen.getByRole('button', { name: /reconnect account/i }));
    expect(startReconnect).toHaveBeenCalled();
  });

  it('falls back to the email when no display name is set', () => {
    renderCard({ display_name: '' });
    expect(screen.getByRole('heading', { level: 3, name: 'me@example.com' })).toBeInTheDocument();
  });

  it('renders inherit-global hint when auto_scan_enabled is null', () => {
    renderCard({ auto_scan_enabled: null });
    expect(screen.getByText(/inherit global/i)).toBeInTheDocument();
  });
});
