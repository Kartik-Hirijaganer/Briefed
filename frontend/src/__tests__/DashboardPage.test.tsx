import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, type RenderResult } from '@testing-library/react';
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
const onlineMock = vi.hoisted(() => ({ value: true }));
vi.mock('../hooks/useOnlineStatus', () => ({ useOnlineStatus: () => onlineMock.value }));
vi.mock('../hooks/usePullToRefresh', () => ({ usePullToRefresh: () => ({}) }));
vi.mock('../hooks/useBreakpoint', () => ({ useBreakpoint: () => 'lg' }));
vi.mock('../features/dashboard/ScanNowButton', () => ({
  ScanNowButton: () => <button data-testid="scan-now">scan</button>,
  SCAN_NOW_EVENT: 'scan-now',
}));

const recentIso = (): string => new Date(Date.now() - 60 * 60 * 1000).toISOString();
const oldIso = (): string => new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString();

const makeEmail = (overrides: Partial<Schemas['EmailRow']> = {}): Schemas['EmailRow'] => ({
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
  ...overrides,
});

const twoEmails = (): readonly Schemas['EmailRow'][] => [
  makeEmail({ id: 'a', subject: 'Call tomorrow', sender: 'lead@example.com' }),
  makeEmail({
    id: 'b',
    subject: 'Weekly newsletter',
    sender: 'news@example.com',
    bucket: 'good_to_read',
    needs_review: false,
  }),
];

const digest: Schemas['DigestToday'] = {
  generated_at: recentIso(),
  last_successful_run_at: recentIso(),
  counts: { must_read: 3, good_to_read: 7, ignore: 12 },
  rule_decided: 5,
  category_summaries: [],
  cost_cents_today: 47,
  must_read_preview: [],
};

const renderPage = (initialEntry = '/'): RenderResult => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
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
  const emailRows = options.emails ?? [makeEmail()];
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
    onlineMock.value = true;
  });

  it('renders the overview band: title, synced cost, filter pills, and scan control', async () => {
    mockDashboardRequests();
    renderPage();

    // The overview band (incl. the title) is skeletoned until the digest loads.
    expect(await screen.findByText("Today's Digest")).toBeInTheDocument();
    expect(screen.getByText(/\$0\.47/)).toBeInTheDocument();
    expect(screen.getByText(/Synced .* ago/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^all/i })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('scan-now')).toBeInTheDocument();
  });

  it('filter pills change the email query bucket and clear it for All', async () => {
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

    await user.click(await screen.findByRole('button', { name: 'Next' }));
    await waitFor(() =>
      expect(apiMock.GET).toHaveBeenCalledWith('/api/v1/emails', {
        params: { query: { offset: 25, limit: 25 } },
      }),
    );
  });

  it('selecting a list row updates the reading pane', async () => {
    const user = userEvent.setup();
    mockDashboardRequests({
      emails: [
        makeEmail({ id: 'a', subject: 'Call tomorrow', sender: 'lead@example.com' }),
        makeEmail({
          id: 'b',
          subject: 'Weekly newsletter',
          sender: 'news@example.com',
          bucket: 'good_to_read',
          needs_review: false,
        }),
      ],
    });
    renderPage();

    // Default selection is the first row.
    expect(await screen.findByRole('heading', { name: /call tomorrow/i })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /weekly newsletter/i }));
    expect(await screen.findByRole('heading', { name: /weekly newsletter/i })).toBeInTheDocument();
  });

  it('shows the why-sorted banner and toggles the review caveat with needs_review', async () => {
    const user = userEvent.setup();
    mockDashboardRequests({
      emails: [
        makeEmail({
          id: 'a',
          subject: 'Call tomorrow',
          needs_review: true,
          reasons: ['sender rule'],
        }),
        makeEmail({
          id: 'b',
          subject: 'Weekly newsletter',
          sender: 'news@example.com',
          bucket: 'good_to_read',
          needs_review: false,
          reasons: ['newsletter rule'],
        }),
      ],
    });
    renderPage();

    expect(await screen.findByText(/Marked Must-Read — sender rule/)).toBeInTheDocument();
    expect(screen.getByText(/double-check before acting/i)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /weekly newsletter/i }));
    await screen.findByRole('heading', { name: /weekly newsletter/i });
    expect(screen.queryByText(/double-check before acting/i)).not.toBeInTheDocument();
  });

  it('shows reading-pane skeletons while the emails query is pending', async () => {
    apiMock.GET.mockImplementation((path: string) => {
      if (path === '/api/v1/digest/today') return Promise.resolve({ data: digest });
      if (path === '/api/v1/emails') return new Promise(() => undefined);
      return Promise.resolve({ data: {} });
    });
    const { container } = renderPage();

    await screen.findByText("Today's Digest");
    expect(container.querySelector('.animate-pulse')).not.toBeNull();
    expect(screen.queryByRole('heading', { name: /call tomorrow/i })).not.toBeInTheDocument();
  });

  it('advances the selection to the next must-read row', async () => {
    const user = userEvent.setup();
    mockDashboardRequests({
      emails: [
        makeEmail({ id: 'a', subject: 'First must read', bucket: 'must_read' }),
        makeEmail({ id: 'b', subject: 'A quiet note', bucket: 'ignore', needs_review: false }),
        makeEmail({
          id: 'c',
          subject: 'Second must read',
          bucket: 'must_read',
          needs_review: false,
        }),
      ],
    });
    renderPage();

    await screen.findByRole('heading', { name: /first must read/i });
    await user.click(screen.getByRole('button', { name: /next must-read/i }));
    expect(await screen.findByRole('heading', { name: /second must read/i })).toBeInTheDocument();
  });

  it('marks the selected email read, optimistically removes it, and advances selection', async () => {
    const user = userEvent.setup();
    mockDashboardRequests({
      emails: [
        makeEmail({ id: 'a', subject: 'Call tomorrow' }),
        makeEmail({
          id: 'b',
          subject: 'Weekly newsletter',
          bucket: 'good_to_read',
          needs_review: false,
        }),
      ],
    });
    apiMock.POST.mockReturnValue(new Promise(() => undefined));
    renderPage();

    await screen.findByRole('heading', { name: /call tomorrow/i });
    await user.click(screen.getByRole('button', { name: /mark read/i }));

    await waitFor(() => expect(screen.queryByText('Call tomorrow')).not.toBeInTheDocument());
    expect(screen.getByRole('heading', { name: /weekly newsletter/i })).toBeInTheDocument();
    expect(apiMock.POST).toHaveBeenCalledWith('/api/v1/emails/mark-read', {
      body: { email_ids: ['a'] },
    });
  });

  it('prompts Gmail reconnect when mark-read needs new authorization', async () => {
    const user = userEvent.setup();
    mockDashboardRequests();
    apiMock.POST.mockResolvedValue({
      error: {
        code: 'gmail_reauthorization_required',
        message: 'Gmail re-authorization is required before mark-read.',
        details: { accountId: 'account-1', scope: 'gmail.modify' },
        requestId: 'request-409',
      },
      response: { status: 409 },
    });
    renderPage();

    await screen.findByRole('heading', { name: /call tomorrow/i });
    await user.click(screen.getByRole('button', { name: /mark read/i }));

    expect(await screen.findByText(/reconnect gmail to mark mail read/i)).toBeInTheDocument();
    expect(
      screen.getByText('Gmail re-authorization is required before mark-read.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /reconnect gmail/i })).toBeInTheDocument();
  });

  it('renders the empty state when no emails are in the view', async () => {
    mockDashboardRequests({ emails: [] });
    renderPage();
    expect(await screen.findByText(/no unread emails in this view/i)).toBeInTheDocument();
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
      return Promise.resolve({ data: { emails: [], total: 0 } });
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/could not load today's digest/i)).toBeInTheDocument(),
    );
  });

  it('renders a checkbox per row and a disabled mark-all button before any selection', async () => {
    mockDashboardRequests({ emails: twoEmails() });
    renderPage();

    await screen.findByRole('heading', { name: /call tomorrow/i });
    expect(
      screen.getByRole('checkbox', { name: /select all visible emails/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('checkbox', { name: /select email from .*call tomorrow/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('checkbox', { name: /select email from .*weekly newsletter/i }),
    ).toBeInTheDocument();
    expect(screen.getByText('2 unread')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^mark all read$/i })).toBeDisabled();
  });

  it('select-all checks every row and marks every visible id', async () => {
    const user = userEvent.setup();
    mockDashboardRequests({ emails: twoEmails() });
    apiMock.POST.mockReturnValue(new Promise(() => undefined));
    renderPage();

    await screen.findByRole('heading', { name: /call tomorrow/i });
    await user.click(screen.getByRole('checkbox', { name: /select all visible emails/i }));

    expect(
      screen.getByRole('checkbox', { name: /select email from .*call tomorrow/i }),
    ).toBeChecked();
    expect(
      screen.getByRole('checkbox', { name: /select email from .*weekly newsletter/i }),
    ).toBeChecked();

    await user.click(screen.getByRole('button', { name: /^mark all read$/i }));
    expect(apiMock.POST).toHaveBeenCalledWith('/api/v1/emails/mark-read', {
      body: { email_ids: ['a', 'b'] },
    });
  });

  it('marking a subset posts only the checked ids and optimistically removes them', async () => {
    const user = userEvent.setup();
    mockDashboardRequests({ emails: twoEmails() });
    apiMock.POST.mockReturnValue(new Promise(() => undefined));
    renderPage();

    await screen.findByRole('heading', { name: /call tomorrow/i });
    await user.click(
      screen.getByRole('checkbox', { name: /select email from .*weekly newsletter/i }),
    );

    // The select-all header reflects the partial selection.
    const selectAll = screen.getByRole('checkbox', { name: /select all visible emails/i });
    expect((selectAll as HTMLInputElement).indeterminate).toBe(true);

    await user.click(screen.getByRole('button', { name: /^mark 1 read$/i }));
    expect(apiMock.POST).toHaveBeenCalledWith('/api/v1/emails/mark-read', {
      body: { email_ids: ['b'] },
    });
    await waitFor(() => expect(screen.queryByText('Weekly newsletter')).not.toBeInTheDocument());
    // The unchecked row stays in the list.
    expect(
      screen.getByRole('checkbox', { name: /select email from .*call tomorrow/i }),
    ).toBeInTheDocument();
  });

  it('surfaces a partial-failure banner from the bulk response', async () => {
    const user = userEvent.setup();
    mockDashboardRequests({ emails: twoEmails() });
    apiMock.POST.mockResolvedValue({
      data: {
        marked: 1,
        failed: [{ email_id: 'b', provider_message_id: 'm-b', reason: 'missing' }],
      },
    });
    renderPage();

    await screen.findByRole('heading', { name: /call tomorrow/i });
    await user.click(screen.getByRole('checkbox', { name: /select all visible emails/i }));
    await user.click(screen.getByRole('button', { name: /^mark all read$/i }));

    expect(await screen.findByText(/could not be updated/i)).toBeInTheDocument();
  });

  it('restores the row and the selection when the bulk request fails', async () => {
    const user = userEvent.setup();
    mockDashboardRequests({ emails: twoEmails() });
    apiMock.POST.mockResolvedValue({ error: { detail: 'boom' }, response: { status: 500 } });
    renderPage();

    await screen.findByRole('heading', { name: /call tomorrow/i });
    await user.click(
      screen.getByRole('checkbox', { name: /select email from .*weekly newsletter/i }),
    );
    await user.click(screen.getByRole('button', { name: /^mark 1 read$/i }));

    expect(await screen.findByText(/could not mark mail read/i)).toBeInTheDocument();
    const restored = await screen.findByRole('checkbox', {
      name: /select email from .*weekly newsletter/i,
    });
    expect(restored).toBeChecked();
  });

  it('clears the selection when the bucket filter changes', async () => {
    const user = userEvent.setup();
    mockDashboardRequests({ emails: twoEmails() });
    renderPage();

    await screen.findByRole('heading', { name: /call tomorrow/i });
    await user.click(screen.getByRole('checkbox', { name: /select email from .*call tomorrow/i }));
    expect(screen.getByRole('button', { name: /^mark 1 read$/i })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /good-to-read/i }));

    expect(await screen.findByRole('button', { name: /^mark all read$/i })).toBeDisabled();
  });

  it('clears the selection when the page changes', async () => {
    const user = userEvent.setup();
    mockDashboardRequests({ emails: twoEmails(), total: 50 });
    renderPage();

    await screen.findByRole('heading', { name: /call tomorrow/i });
    await user.click(screen.getByRole('checkbox', { name: /select email from .*call tomorrow/i }));
    expect(screen.getByRole('button', { name: /^mark 1 read$/i })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Next' }));

    expect(await screen.findByRole('button', { name: /^mark all read$/i })).toBeDisabled();
  });

  it('toggles bulk selection without opening the reader; the row body still opens it', async () => {
    const user = userEvent.setup();
    mockDashboardRequests({ emails: twoEmails() });
    renderPage();

    // Default reader selection is the first row.
    await screen.findByRole('heading', { name: /call tomorrow/i });

    // Checking the second row does not change the reading pane.
    await user.click(
      screen.getByRole('checkbox', { name: /select email from .*weekly newsletter/i }),
    );
    expect(
      screen.getByRole('checkbox', { name: /select email from .*weekly newsletter/i }),
    ).toBeChecked();
    expect(screen.getByRole('heading', { name: /call tomorrow/i })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: /weekly newsletter/i })).not.toBeInTheDocument();

    // Clicking the row body opens it in the reader.
    await user.click(screen.getByRole('button', { name: /weekly newsletter/i }));
    expect(await screen.findByRole('heading', { name: /weekly newsletter/i })).toBeInTheDocument();
  });

  it('disables bulk and single mark-read while offline', async () => {
    onlineMock.value = false;
    const user = userEvent.setup();
    mockDashboardRequests({ emails: twoEmails() });
    renderPage();

    await screen.findByRole('heading', { name: /call tomorrow/i });
    await user.click(screen.getByRole('checkbox', { name: /select all visible emails/i }));

    expect(screen.getByRole('button', { name: /^mark all read$/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /^mark read$/i })).toBeDisabled();
  });
});
