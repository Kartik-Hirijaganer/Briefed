import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type * as ApiClient from '../api/client';
import DashboardPage from '../pages/DashboardPage';

const apiMock = vi.hoisted(() => ({ GET: vi.fn() }));

vi.mock('../api/client', async (importOriginal) => {
  const actual = (await importOriginal()) as typeof ApiClient;
  return { ...actual, api: apiMock };
});

vi.mock('../hooks/useFreshnessState', () => ({
  useFreshnessState: () => ({ state: 'fresh', lastKnownGoodAt: null }),
}));
vi.mock('../hooks/useOnlineStatus', () => ({ useOnlineStatus: () => true }));
vi.mock('../hooks/usePullToRefresh', () => ({
  usePullToRefresh: () => ({}),
}));

vi.mock('../features/email/EmailCard', () => ({
  EmailCard: ({ email }: { email: { id: string; subject: string } }) => (
    <div data-testid={`email-${email.id}`}>{email.subject}</div>
  ),
}));

vi.mock('../features/dashboard/ScanNowButton', () => ({
  ScanNowButton: () => <button data-testid="scan-now">scan</button>,
  SCAN_NOW_EVENT: 'scan-now',
}));

const renderPage = (): void => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
};

const recentIso = (): string => new Date(Date.now() - 60 * 60 * 1000).toISOString();
const oldIso = (): string => new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString();

describe('<DashboardPage>', () => {
  beforeEach(() => apiMock.GET.mockReset());

  it('renders stat tiles, today cost and must-read preview', async () => {
    apiMock.GET.mockResolvedValue({
      data: {
        last_successful_run_at: recentIso(),
        counts: { must_read: 3, good_to_read: 7, ignore: 12 },
        cost_cents_today: 47,
        must_read_preview: [
          { id: 'e1', subject: 'Call tomorrow' },
          { id: 'e2', subject: 'Invoice due' },
        ],
      },
    });
    renderPage();
    expect(screen.getByText("Today's Digest")).toBeInTheDocument();
    expect(await screen.findByText('Must read')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getByText('$0.47')).toBeInTheDocument();
    expect(screen.getByTestId('email-e1')).toBeInTheDocument();
    expect(screen.getByTestId('scan-now')).toBeInTheDocument();
  });

  it('renders the inbox-zero empty state when must-read preview is empty', async () => {
    apiMock.GET.mockResolvedValue({
      data: {
        last_successful_run_at: recentIso(),
        counts: { must_read: 0, good_to_read: 0, ignore: 0 },
        cost_cents_today: 0,
        must_read_preview: [],
      },
    });
    renderPage();
    await waitFor(() => expect(screen.getByText(/inbox zero for today/i)).toBeInTheDocument());
  });

  it('shows the auto-scan-off alert when the last run is older than 7 days', async () => {
    apiMock.GET.mockResolvedValue({
      data: {
        last_successful_run_at: oldIso(),
        counts: { must_read: 0, good_to_read: 0, ignore: 0 },
        cost_cents_today: 0,
        must_read_preview: [],
      },
    });
    renderPage();
    await waitFor(() => expect(screen.getByText(/auto-scan may be off/i)).toBeInTheDocument());
  });

  it('renders the error state on a failed fetch', async () => {
    apiMock.GET.mockResolvedValue({ error: { detail: 'down' }, response: { status: 500 } });
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/could not load today's digest/i)).toBeInTheDocument(),
    );
  });
});
