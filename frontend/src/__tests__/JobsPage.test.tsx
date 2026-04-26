import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type * as ApiClient from '../api/client';
import JobsPage from '../pages/JobsPage';

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
      <JobsPage />
    </QueryClientProvider>,
  );
};

const job = (overrides: Partial<Record<string, unknown>> = {}): Record<string, unknown> => ({
  id: 'j1',
  title: 'Senior ML',
  company: 'Acme',
  location: 'Remote',
  comp_min: 200000,
  comp_max: 300000,
  currency: 'USD',
  match_score: 0.87,
  match_reason: 'matches your filter',
  passed_filter: true,
  source_url: 'https://jobs.example.com/123',
  ...overrides,
});

describe('<JobsPage>', () => {
  beforeEach(() => apiMock.GET.mockReset());

  it('renders matched jobs with score badge and source link', async () => {
    apiMock.GET.mockResolvedValue({ data: { matches: [job()] } });
    renderPage();
    await waitFor(() => expect(screen.getByText(/Senior ML — Acme/)).toBeInTheDocument());
    expect(screen.getByText('87%')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /open posting/i })).toHaveAttribute(
      'href',
      'https://jobs.example.com/123',
    );
    expect(screen.getByText(/USD 200,000-300,000/)).toBeInTheDocument();
  });

  it('toggles to "All" and refetches with include_filtered=true', async () => {
    apiMock.GET.mockResolvedValue({ data: { matches: [job()] } });
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(screen.getByText(/Senior ML/)).toBeInTheDocument());
    apiMock.GET.mockClear();
    apiMock.GET.mockResolvedValue({ data: { matches: [] } });
    await user.click(screen.getByRole('button', { name: /^all$/i }));
    await waitFor(() => expect(apiMock.GET).toHaveBeenCalled());
    expect(apiMock.GET).toHaveBeenCalledWith('/api/v1/jobs', {
      params: { query: { include_filtered: true } },
    });
  });

  it('renders salary fallback strings', async () => {
    apiMock.GET.mockResolvedValue({
      data: {
        matches: [
          job({
            id: 'j2',
            comp_min: null,
            comp_max: null,
            currency: null,
            location: null,
            passed_filter: false,
            source_url: null,
          }),
        ],
      },
    });
    renderPage();
    await waitFor(() => expect(screen.getByText(/Senior ML — Acme/)).toBeInTheDocument());
    expect(screen.getByText(/Remote \/ unspecified · Salary n\/a/)).toBeInTheDocument();
  });

  it('renders the empty state when no jobs', async () => {
    apiMock.GET.mockResolvedValue({ data: { matches: [] } });
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/no jobs passed your filter today/i)).toBeInTheDocument(),
    );
  });

  it('renders the error state on a failed fetch', async () => {
    apiMock.GET.mockResolvedValue({ error: { detail: 'down' }, response: { status: 500 } });
    renderPage();
    await waitFor(() => expect(screen.getByText(/could not load jobs/i)).toBeInTheDocument());
  });
});
