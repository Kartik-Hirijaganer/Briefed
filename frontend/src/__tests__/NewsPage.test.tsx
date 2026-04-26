import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type * as ApiClient from '../api/client';
import NewsPage from '../pages/NewsPage';

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
      <NewsPage />
    </QueryClientProvider>,
  );
};

describe('<NewsPage>', () => {
  beforeEach(() => apiMock.GET.mockReset());

  it('renders one card per cluster', async () => {
    apiMock.GET.mockResolvedValue({
      data: {
        clusters: [
          {
            id: 'c1',
            label: 'AI roundup',
            summary_md: 'three things in AI',
            email_ids: ['e1', 'e2', 'e3'],
          },
          {
            id: 'c2',
            label: 'Frontend tooling',
            summary_md: 'vite vs turbopack',
            email_ids: ['e4'],
          },
        ],
      },
    });
    renderPage();
    await waitFor(() => expect(screen.getByText('AI roundup')).toBeInTheDocument());
    expect(screen.getByText('Frontend tooling')).toBeInTheDocument();
    expect(screen.getByText('Clustered from 3 emails')).toBeInTheDocument();
    expect(screen.getByText('Clustered from 1 emails')).toBeInTheDocument();
  });

  it('renders the empty state when no clusters', async () => {
    apiMock.GET.mockResolvedValue({ data: { clusters: [] } });
    renderPage();
    await waitFor(() => expect(screen.getByText(/no news digests yet/i)).toBeInTheDocument());
  });

  it('renders the error state on a failed fetch', async () => {
    apiMock.GET.mockResolvedValue({ error: { detail: 'down' }, response: { status: 500 } });
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/could not load news digest/i)).toBeInTheDocument(),
    );
  });
});
