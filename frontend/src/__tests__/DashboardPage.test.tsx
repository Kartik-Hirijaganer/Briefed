import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type * as ApiClient from '../api/client';
import type { Schemas } from '../api/types';
import DashboardPage from '../pages/DashboardPage';

const apiMock = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }));

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

vi.mock('../features/dashboard/ScanNowButton', () => ({
  ScanNowButton: () => <button data-testid="scan-now">scan</button>,
  SCAN_NOW_EVENT: 'scan-now',
}));

const recentIso = (): string => new Date(Date.now() - 60 * 60 * 1000).toISOString();
const oldIso = (): string => new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString();

const baseEmail: Schemas['EmailRow'] = {
  id: 'e1',
  account_email: 'me@example.com',
  thread_id: 'thread-1',
  subject: 'Call tomorrow',
  sender: 'lead@example.com',
  received_at: '2026-05-31T14:00:00Z',
  bucket: 'must_read',
  confidence: 0.72,
  needs_review: true,
  decision_source: 'rule',
  reasons: ['sender rule'],
  summary_excerpt: 'Confirm the call agenda.',
};

const digest: Schemas['DigestToday'] = {
  generated_at: recentIso(),
  last_successful_run_at: recentIso(),
  counts: { must_read: 3, good_to_read: 7, ignore: 12 },
  rule_decided: 5,
  category_summaries: [
    {
      category: 'must_read',
      narrative: '**Three** things need attention.',
      confidence: 0.91,
      groups: [{ label: 'People', bullets: ['Reply to the call thread.'], item_refs: ['e1'] }],
    },
    {
      category: 'good_to_read',
      narrative: 'Newsletter roundup is ready.',
      confidence: 0.84,
      groups: [],
    },
  ],
  cost_cents_today: 47,
  must_read_preview: [],
};

const emailsResponse = (emails: readonly Schemas['EmailRow'][]): Schemas['EmailsListResponse'] => ({
  emails: [...emails],
  total: emails.length,
});

const renderPage = (initialEntry = '/'): void => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <DashboardPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
};

const mockDashboardRequests = (
  options: {
    readonly digest?: Schemas['DigestToday'];
    readonly emails?: readonly Schemas['EmailRow'][];
    readonly total?: number;
  } = {},
): void => {
  const digestData = options.digest ?? digest;
  const emailRows = options.emails ?? [baseEmail];
  apiMock.GET.mockImplementation((path: string) => {
    if (path === '/api/v1/digest/today') return Promise.resolve({ data: digestData });
    if (path === '/api/v1/emails') {
      return Promise.resolve({
        data: { emails: [...emailRows], total: options.total ?? emailRows.length },
      });
    }
    return Promise.resolve({ data: {} });
  });
};

describe('<DashboardPage>', () => {
  beforeEach(() => {
    apiMock.GET.mockReset();
    apiMock.POST.mockReset();
  });

  it('renders narrative cards, KPI filters, rules-sorted stat, and tagged table rows', async () => {
    mockDashboardRequests();
    renderPage();

    expect(screen.getByText("Today's Digest")).toBeInTheDocument();
    expect((await screen.findAllByText('Must-Read')).length).toBeGreaterThan(0);
    expect(screen.getByText(/5 sorted by your rules/)).toBeInTheDocument();
    expect(screen.getByText(/today's cost: \$0\.47/i)).toBeInTheDocument();
    expect(screen.getByText('Three')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /all/i })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getAllByText('Call tomorrow').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Must-Read').length).toBeGreaterThan(1);
    expect(screen.getAllByText(/double-check/i).length).toBeGreaterThan(0);
    expect(screen.getByTestId('scan-now')).toBeInTheDocument();
  });

  it('hides empty narrative summaries while keeping the table visible', async () => {
    mockDashboardRequests({ digest: { ...digest, category_summaries: [] }, emails: [] });
    renderPage();

    expect(await screen.findByRole('heading', { name: /all emails/i })).toBeInTheDocument();
    expect(screen.queryByText('Three')).not.toBeInTheDocument();
    expect(screen.getByText(/no unread emails in this view/i)).toBeInTheDocument();
  });

  it('KPI clicks update the email query bucket and clear it for All', async () => {
    const user = userEvent.setup();
    mockDashboardRequests();
    renderPage();

    await user.click(await screen.findByRole('button', { name: /good-to-read/i }));
    await waitFor(() =>
      expect(apiMock.GET).toHaveBeenCalledWith('/api/v1/emails', {
        params: { query: { bucket: 'good_to_read', offset: 0, limit: 25 } },
      }),
    );

    await user.click(screen.getByRole('button', { name: /^all/i }));
    await waitFor(() =>
      expect(apiMock.GET).toHaveBeenCalledWith('/api/v1/emails', {
        params: { query: { offset: 0, limit: 25 } },
      }),
    );
  });

  it('pagination advances the offset query', async () => {
    const user = userEvent.setup();
    mockDashboardRequests({ total: 50 });
    renderPage();

    await user.click(await screen.findByRole('button', { name: /next/i }));
    await waitFor(() =>
      expect(apiMock.GET).toHaveBeenCalledWith('/api/v1/emails', {
        params: { query: { offset: 25, limit: 25 } },
      }),
    );
  });

  it('marks one row read through the mark-read endpoint', async () => {
    const user = userEvent.setup();
    mockDashboardRequests();
    apiMock.POST.mockResolvedValue({ data: { marked: 1, failed: [] } });
    renderPage();

    const row = await screen.findByRole('row', { name: /call tomorrow/i });
    await user.click(within(row).getByRole('button', { name: /mark read/i }));

    await waitFor(() =>
      expect(apiMock.POST).toHaveBeenCalledWith('/api/v1/emails/mark-read', {
        body: { email_ids: ['e1'] },
      }),
    );
  });

  it('bulk select-all optimistically removes selected rows before mark-read settles', async () => {
    const user = userEvent.setup();
    mockDashboardRequests();
    apiMock.POST.mockReturnValue(new Promise(() => undefined));
    renderPage();

    await screen.findAllByText('Call tomorrow');
    await user.click(screen.getByRole('checkbox', { name: /select all visible emails/i }));
    await user.click(screen.getByRole('button', { name: /mark selected read/i }));

    await waitFor(() => expect(screen.queryByText('Call tomorrow')).not.toBeInTheDocument());
    expect(apiMock.POST).toHaveBeenCalledWith('/api/v1/emails/mark-read', {
      body: { email_ids: ['e1'] },
    });
  });

  it('shows the auto-scan-off alert when the last run is older than 7 days', async () => {
    mockDashboardRequests({ digest: { ...digest, last_successful_run_at: oldIso() } });
    renderPage();
    await waitFor(() => expect(screen.getByText(/auto-scan may be off/i)).toBeInTheDocument());
  });

  it('renders the error state on a failed digest fetch', async () => {
    apiMock.GET.mockImplementation((path: string) => {
      if (path === '/api/v1/digest/today') {
        return Promise.resolve({ error: { detail: 'down' }, response: { status: 500 } });
      }
      return Promise.resolve({ data: emailsResponse([]) });
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/could not load today's digest/i)).toBeInTheDocument(),
    );
  });
});
