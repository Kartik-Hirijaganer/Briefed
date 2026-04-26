import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type * as ApiClient from '../api/client';
import HistoryPage from '../pages/HistoryPage';

const apiMock = vi.hoisted(() => ({ GET: vi.fn() }));

vi.mock('../api/client', async (importOriginal) => {
  const actual = (await importOriginal()) as typeof ApiClient;
  return { ...actual, api: apiMock };
});

vi.mock('../hooks/useFreshnessState', () => ({
  useFreshnessState: () => ({ state: 'fresh', lastKnownGoodAt: null }),
}));

const renderPage = (): void => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <HistoryPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
};

describe('<HistoryPage>', () => {
  beforeEach(() => apiMock.GET.mockReset());

  it('renders one row per run with status badge and cost', async () => {
    apiMock.GET.mockResolvedValue({
      data: {
        runs: [
          {
            id: 'r1',
            status: 'complete',
            trigger_type: 'scheduled',
            started_at: '2026-04-25T10:00:00Z',
            stats: { ingested: 12, classified: 12, summarized: 4 },
            cost_cents: 25,
          },
          {
            id: 'r2',
            status: 'failed',
            trigger_type: 'manual',
            started_at: '2026-04-24T10:00:00Z',
            stats: { ingested: 0, classified: 0, summarized: 0 },
            error: 'rate limited',
          },
        ],
      },
    });
    renderPage();
    await waitFor(() => expect(screen.getByText('complete')).toBeInTheDocument());
    expect(screen.getByText('failed')).toBeInTheDocument();
    expect(screen.getByText('rate limited')).toBeInTheDocument();
    expect(screen.getByText('$0.25')).toBeInTheDocument();
    expect(screen.getByText('Ingested 12')).toBeInTheDocument();
  });

  it('renders the empty state when no runs', async () => {
    apiMock.GET.mockResolvedValue({ data: { runs: [] } });
    renderPage();
    await waitFor(() => expect(screen.getByText(/no runs yet/i)).toBeInTheDocument());
  });

  it('renders the error state on a failed fetch', async () => {
    apiMock.GET.mockResolvedValue({ error: { detail: 'oops' }, response: { status: 500 } });
    renderPage();
    await waitFor(() => expect(screen.getByText(/could not load history/i)).toBeInTheDocument());
  });
});
