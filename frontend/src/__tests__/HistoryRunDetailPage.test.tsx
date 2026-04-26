import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type * as ApiClient from '../api/client';
import HistoryRunDetailPage from '../pages/HistoryRunDetailPage';

const apiMock = vi.hoisted(() => ({
  GET: vi.fn(),
}));

vi.mock('../api/client', async (importOriginal) => {
  const actual = (await importOriginal()) as typeof ApiClient;
  return { ...actual, api: apiMock };
});

const renderAt = (path: string): void => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/history/:runId" element={<HistoryRunDetailPage />} />
          <Route path="/history" element={<div>history</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
};

describe('<HistoryRunDetailPage>', () => {
  beforeEach(() => {
    apiMock.GET.mockReset();
  });

  it('renders stage timeline and cost from RunStatusResponse', async () => {
    apiMock.GET.mockResolvedValue({
      data: {
        id: '11111111-1111-1111-1111-111111111111',
        status: 'complete',
        trigger_type: 'manual',
        started_at: '2026-04-25T10:00:00Z',
        completed_at: '2026-04-25T10:02:30Z',
        stats: { ingested: 47, classified: 47, summarized: 12, new_must_read: 3 },
        cost_cents: 87,
      },
    });
    renderAt('/history/11111111-1111-1111-1111-111111111111');
    await waitFor(() => expect(screen.getByText('Stage timeline')).toBeInTheDocument());
    expect(screen.getByText('Ingested')).toBeInTheDocument();
    expect(screen.getAllByText('47')).toHaveLength(2);
    expect(screen.getByText('$0.87')).toBeInTheDocument();
    expect(apiMock.GET).toHaveBeenCalledWith('/api/v1/runs/{run_id}', {
      params: { path: { run_id: '11111111-1111-1111-1111-111111111111' } },
    });
  });

  it('shows the run-level error block when the run failed', async () => {
    apiMock.GET.mockResolvedValue({
      data: {
        id: 'abc',
        status: 'failed',
        trigger_type: 'scheduled',
        started_at: '2026-04-25T09:00:00Z',
        completed_at: '2026-04-25T09:00:30Z',
        stats: { ingested: 0, classified: 0, summarized: 0, new_must_read: 0 },
        error: 'Gmail rate-limited',
      },
    });
    renderAt('/history/abc');
    await waitFor(() => expect(screen.getByText('Gmail rate-limited')).toBeInTheDocument());
  });
});
