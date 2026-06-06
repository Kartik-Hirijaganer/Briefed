import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type * as ApiClient from '../api/client';
import type { Schemas } from '../api/types';
import UnsubscribePage from '../pages/UnsubscribePage';

const apiMock = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }));
const onlineMock = vi.hoisted(() => ({ value: true }));
const enqueueMock = vi.hoisted(() => vi.fn());

vi.mock('../api/client', async (importOriginal) => {
  const actual = (await importOriginal()) as typeof ApiClient;
  return { ...actual, api: apiMock };
});
vi.mock('../hooks/useFreshnessState', () => ({
  useFreshnessState: () => ({ state: 'fresh', lastKnownGoodAt: null }),
}));
vi.mock('../hooks/useOnlineStatus', () => ({ useOnlineStatus: () => onlineMock.value }));
vi.mock('../offline/mutations', () => ({ enqueueMutation: enqueueMock }));

type Suggestion = Schemas['UnsubscribeSuggestion'];

const suggestion = (overrides: Partial<Suggestion> = {}): Suggestion => ({
  id: 's1',
  sender_domain: 'news.example',
  sender_email: 'noisy@news.example',
  frequency_30d: 30,
  engagement_score: '0.05',
  waste_rate: '0.80',
  confidence: '0.91',
  decision_source: 'rule',
  category: null,
  rationale: 'opened 0/30',
  list_unsubscribe: { http_urls: ['https://news.example/unsub'], mailto: null, one_click: true },
  dismissed: false,
  dismissed_at: null,
  last_email_at: null,
  created_at: '2026-06-01T00:00:00Z',
  updated_at: '2026-06-01T00:00:00Z',
  recent_subjects: ['Flash sale ends tonight', 'Last chance', 'Weekly promo'],
  ...overrides,
});

const mockRequests = (
  options: {
    suggestions?: readonly Suggestion[];
    pending?: boolean;
    errored?: boolean;
    executeEnabled?: boolean;
  } = {},
): void => {
  apiMock.GET.mockImplementation((path: string) => {
    if (path === '/api/v1/config') {
      return Promise.resolve({ data: { unsubscribe_execute: options.executeEnabled ?? false } });
    }
    if (path === '/api/v1/unsubscribes') {
      if (options.pending) return new Promise(() => undefined);
      if (options.errored)
        return Promise.resolve({ error: { detail: 'down' }, response: { status: 500 } });
      return Promise.resolve({
        data: { suggestions: [...(options.suggestions ?? [suggestion()])] },
      });
    }
    return Promise.resolve({ data: {} });
  });
};

const renderPage = (): ReturnType<typeof render> => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <UnsubscribePage />
    </QueryClientProvider>,
  );
};

describe('<UnsubscribePage>', () => {
  beforeEach(() => {
    apiMock.GET.mockReset();
    apiMock.POST.mockReset();
    apiMock.POST.mockResolvedValue({ data: undefined });
    enqueueMock.mockReset();
    onlineMock.value = true;
  });
  afterEach(() => vi.restoreAllMocks());

  it('renders the derived header counts', async () => {
    mockRequests({
      suggestions: [
        suggestion({ id: 's1', frequency_30d: 30, waste_rate: '0.80' }),
        suggestion({
          id: 's2',
          sender_email: 'b@x.example',
          frequency_30d: 10,
          waste_rate: '0.50',
        }),
      ],
    });
    renderPage();
    // 2 flagged; 30*0.8 + 10*0.5 = 29 wasted/month.
    expect(
      await screen.findByText(/2 senders flagged · ~29 wasted emails \/ month/),
    ).toBeInTheDocument();
  });

  it('renders per-card stats, recent chips, and tags', async () => {
    mockRequests();
    renderPage();
    await screen.findByText('noisy@news.example');
    expect(screen.getByText('30/mo received · 5% opened')).toBeInTheDocument();
    expect(screen.getByText('Flash sale ends tonight')).toBeInTheDocument();
    // freq 30 → noisy; engagement 0.05 → disengaged; waste 0.80 → low value.
    expect(screen.getByText('Noisy')).toBeInTheDocument();
    expect(screen.getByText('Disengaged')).toBeInTheDocument();
    expect(screen.getByText('Low value')).toBeInTheDocument();
  });

  it('tracks selection count and the indeterminate header checkbox', async () => {
    const user = userEvent.setup();
    mockRequests({
      suggestions: [
        suggestion({ id: 's1' }),
        suggestion({ id: 's2', sender_email: 'b@x.example' }),
      ],
    });
    renderPage();
    await screen.findByText('noisy@news.example');

    await user.click(screen.getByRole('checkbox', { name: /select noisy@news\.example/i }));
    expect(screen.getByText('1 of 2 selected')).toBeInTheDocument();
    const headerCheckbox = screen.getByRole('checkbox', {
      name: /select all senders/i,
    }) as HTMLInputElement;
    expect(headerCheckbox.indeterminate).toBe(true);
  });

  it('applies the accent highlight to a selected card', async () => {
    const user = userEvent.setup();
    mockRequests();
    renderPage();
    await screen.findByText('noisy@news.example');
    expect(screen.getByText('noisy@news.example').closest('.border-accent')).toBeNull();
    await user.click(screen.getByRole('checkbox', { name: /select noisy@news\.example/i }));
    expect(screen.getByText('noisy@news.example').closest('.border-accent')).not.toBeNull();
  });

  it('bulk recommend-only opens links and fires N confirm POSTs', async () => {
    const user = userEvent.setup();
    const openSpy = vi.spyOn(window, 'open').mockReturnValue(null);
    mockRequests({
      suggestions: [
        suggestion({ id: 's1' }),
        suggestion({ id: 's2', sender_email: 'b@x.example' }),
      ],
    });
    renderPage();
    await screen.findByText('noisy@news.example');
    await user.click(screen.getByRole('checkbox', { name: /select all senders/i }));
    await user.click(screen.getByRole('button', { name: /unsubscribe 2 selected/i }));

    await waitFor(() => expect(apiMock.POST).toHaveBeenCalledTimes(2));
    expect(openSpy).toHaveBeenCalledTimes(2);
    expect(apiMock.POST).toHaveBeenCalledWith('/api/v1/unsubscribes/{suggestion_id}/confirm', {
      params: { path: { suggestion_id: 's1' } },
    });
  });

  it('bulk keep fires N dismiss POSTs', async () => {
    const user = userEvent.setup();
    mockRequests({
      suggestions: [
        suggestion({ id: 's1' }),
        suggestion({ id: 's2', sender_email: 'b@x.example' }),
      ],
    });
    renderPage();
    await screen.findByText('noisy@news.example');
    await user.click(screen.getByRole('checkbox', { name: /select all senders/i }));
    await user.click(screen.getByRole('button', { name: /keep selected/i }));

    await waitFor(() => expect(apiMock.POST).toHaveBeenCalledTimes(2));
    expect(apiMock.POST).toHaveBeenCalledWith('/api/v1/unsubscribes/{suggestion_id}/dismiss', {
      params: { path: { suggestion_id: 's1' } },
    });
  });

  it('enqueues a dismiss mutation when keeping offline', async () => {
    onlineMock.value = false;
    const user = userEvent.setup();
    mockRequests();
    renderPage();
    await screen.findByText('noisy@news.example');

    await user.click(screen.getByRole('checkbox', { name: /select all senders/i }));
    await user.click(screen.getByRole('button', { name: /keep selected/i }));
    await waitFor(() =>
      expect(enqueueMock).toHaveBeenCalledWith({ type: 'unsubscribe_dismiss', suggestionId: 's1' }),
    );
  });

  it('enqueues a confirm mutation when recommend-only unsubscribing offline', async () => {
    onlineMock.value = false;
    vi.spyOn(window, 'open').mockReturnValue(null);
    const user = userEvent.setup();
    mockRequests();
    renderPage();
    await screen.findByText('noisy@news.example');

    await user.click(screen.getByRole('checkbox', { name: /select all senders/i }));
    await user.click(screen.getByRole('button', { name: /unsubscribe 1 selected/i }));
    await waitFor(() =>
      expect(enqueueMock).toHaveBeenCalledWith({ type: 'unsubscribe_confirm', suggestionId: 's1' }),
    );
  });

  it('renders the empty state when no suggestions', async () => {
    mockRequests({ suggestions: [] });
    renderPage();
    expect(await screen.findByText(/no suggestions right now/i)).toBeInTheDocument();
  });

  it('renders the error state on a failed fetch', async () => {
    mockRequests({ errored: true });
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/could not load suggestions/i)).toBeInTheDocument(),
    );
  });

  it('renders skeletons while loading', () => {
    mockRequests({ pending: true });
    const { container } = renderPage();
    expect(container.querySelector('.animate-pulse')).not.toBeNull();
  });

  // --- Track 5: execute UX (capability on) --------------------------------

  const mockExecutePost = (byId: Record<string, Record<string, unknown>>): void => {
    apiMock.POST.mockImplementation(
      (path: string, opts?: { params?: { path?: { suggestion_id?: string } } }) => {
        if (path.endsWith('/execute')) {
          const id = opts?.params?.path?.suggestion_id ?? '';
          return Promise.resolve({ data: byId[id] });
        }
        return Promise.resolve({ data: undefined });
      },
    );
  };

  it('capability on gates the execute POSTs behind a confirmation dialog', async () => {
    const user = userEvent.setup();
    mockRequests({ executeEnabled: true, suggestions: [suggestion({ id: 's1' })] });
    mockExecutePost({
      s1: { status: 'unsubscribed', executed_via: 'one_click', manual_url: null, message: 'ok' },
    });
    renderPage();
    await screen.findByText('noisy@news.example');

    await user.click(screen.getByRole('checkbox', { name: /select all senders/i }));
    await user.click(screen.getByRole('button', { name: /unsubscribe 1 selected/i }));

    // Dialog gates the action — no execute POST yet.
    expect(await screen.findByText(/unsubscribe from 1 senders\?/i)).toBeInTheDocument();
    expect(apiMock.POST).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Unsubscribe' }));
    await waitFor(() =>
      expect(apiMock.POST).toHaveBeenCalledWith('/api/v1/unsubscribes/{suggestion_id}/execute', {
        params: { path: { suggestion_id: 's1' } },
        body: { confirm: true },
      }),
    );
  });

  it('shows a spinner in the confirmation button while execute is busy', async () => {
    const user = userEvent.setup();
    let resolveExecute:
      | ((value: { data: Schemas['UnsubscribeExecuteResponse'] }) => void)
      | undefined;
    mockRequests({ executeEnabled: true, suggestions: [suggestion({ id: 's1' })] });
    apiMock.POST.mockImplementation((path: string) => {
      if (path.endsWith('/execute')) {
        return new Promise<{ data: Schemas['UnsubscribeExecuteResponse'] }>((resolve) => {
          resolveExecute = resolve;
        });
      }
      return Promise.resolve({ data: undefined });
    });
    renderPage();
    await screen.findByText('noisy@news.example');

    await user.click(screen.getByRole('checkbox', { name: /select all senders/i }));
    await user.click(screen.getByRole('button', { name: /unsubscribe 1 selected/i }));
    await user.click(screen.getByRole('button', { name: 'Unsubscribe' }));

    const confirmButton = screen.getByRole('button', { name: 'Unsubscribe' });
    expect(confirmButton).toHaveAttribute('aria-busy', 'true');
    expect(confirmButton).toBeDisabled();

    resolveExecute?.({
      data: {
        status: 'unsubscribed',
        executed_via: 'one_click',
        manual_url: null,
        message: 'ok',
      },
    });
    await waitFor(() =>
      expect(screen.queryByText(/unsubscribe from 1 senders\?/i)).not.toBeInTheDocument(),
    );
  });

  it('applies per-result transitions and a results summary (no tab spam)', async () => {
    const user = userEvent.setup();
    const openSpy = vi.spyOn(window, 'open').mockReturnValue(null);
    const all = [
      suggestion({ id: 's1', sender_email: 'a@x.example' }),
      suggestion({ id: 's2', sender_email: 'b@x.example' }),
      suggestion({ id: 's3', sender_email: 'c@x.example' }),
    ];
    const byId: Record<string, Record<string, unknown>> = {
      s1: { status: 'unsubscribed', executed_via: 'one_click', manual_url: null, message: 'done' },
      s2: {
        status: 'manual_required',
        executed_via: 'none',
        manual_url: 'https://m.example/u',
        message: 'Finish in your browser.',
      },
      s3: { status: 'failed', executed_via: 'none', manual_url: null, message: 'Sender error.' },
    };
    // Stateful mock: an `unsubscribed` execute dismisses the row server-side, so
    // the post-batch invalidation refetch excludes it (mirrors the backend).
    const dismissed = new Set<string>();
    apiMock.GET.mockImplementation((path: string) => {
      if (path === '/api/v1/config') {
        return Promise.resolve({ data: { unsubscribe_execute: true } });
      }
      if (path === '/api/v1/unsubscribes') {
        return Promise.resolve({ data: { suggestions: all.filter((s) => !dismissed.has(s.id)) } });
      }
      return Promise.resolve({ data: {} });
    });
    apiMock.POST.mockImplementation(
      (path: string, opts?: { params?: { path?: { suggestion_id?: string } } }) => {
        if (path.endsWith('/execute')) {
          const id = opts?.params?.path?.suggestion_id ?? '';
          if (byId[id]?.status === 'unsubscribed') dismissed.add(id);
          return Promise.resolve({ data: byId[id] });
        }
        return Promise.resolve({ data: undefined });
      },
    );
    renderPage();
    await screen.findByText('a@x.example');

    await user.click(screen.getByRole('checkbox', { name: /select all senders/i }));
    await user.click(screen.getByRole('button', { name: /unsubscribe 3 selected/i }));
    await user.click(screen.getByRole('button', { name: 'Unsubscribe' }));

    // s1 unsubscribed → removed; s2/s3 kept with follow-ups.
    await waitFor(() => expect(screen.queryByText('a@x.example')).not.toBeInTheDocument());
    expect(screen.getByText('b@x.example')).toBeInTheDocument();
    expect(screen.getByText('c@x.example')).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: /open unsubscribe page/i }).length).toBeGreaterThan(
      0,
    );
    expect(screen.getByRole('button', { name: /i've unsubscribed/i })).toBeInTheDocument();
    expect(screen.getByText('Sender error.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
    expect(
      screen.getByText(/1 unsubscribed · 1 need a manual step · 1 failed/),
    ).toBeInTheDocument();

    // Execute never auto-opens tabs.
    expect(openSpy).not.toHaveBeenCalled();
  });

  it('disables the execute primary when offline (capability on)', async () => {
    onlineMock.value = false;
    const user = userEvent.setup();
    mockRequests({ executeEnabled: true });
    renderPage();
    await screen.findByText('noisy@news.example');
    await user.click(screen.getByRole('checkbox', { name: /select all senders/i }));
    expect(screen.getByRole('button', { name: /unsubscribe 1 selected/i })).toBeDisabled();
  });

  it('marks a manual_required row handled via the confirm endpoint', async () => {
    const user = userEvent.setup();
    mockRequests({ executeEnabled: true, suggestions: [suggestion({ id: 's1' })] });
    mockExecutePost({
      s1: {
        status: 'manual_required',
        executed_via: 'none',
        manual_url: 'https://m.example/u',
        message: 'Finish in your browser.',
      },
    });
    renderPage();
    await screen.findByText('noisy@news.example');
    await user.click(screen.getByRole('checkbox', { name: /select all senders/i }));
    await user.click(screen.getByRole('button', { name: /unsubscribe 1 selected/i }));
    await user.click(screen.getByRole('button', { name: 'Unsubscribe' }));

    await screen.findByRole('button', { name: /i've unsubscribed/i });
    await user.click(screen.getByRole('button', { name: /i've unsubscribed/i }));
    await waitFor(() =>
      expect(apiMock.POST).toHaveBeenCalledWith('/api/v1/unsubscribes/{suggestion_id}/confirm', {
        params: { path: { suggestion_id: 's1' } },
      }),
    );
  });
});
