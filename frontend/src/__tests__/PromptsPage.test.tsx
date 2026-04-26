import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type * as ApiClient from '../api/client';
import PromptsPage from '../pages/settings/PromptsPage';

const apiMock = vi.hoisted(() => ({ GET: vi.fn() }));

vi.mock('../api/client', async (importOriginal) => {
  const actual = (await importOriginal()) as typeof ApiClient;
  return { ...actual, api: apiMock };
});

const renderPage = (): void => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <PromptsPage />
    </QueryClientProvider>,
  );
};

describe('<PromptsPage>', () => {
  beforeEach(() => apiMock.GET.mockReset());

  it('renders one card per rubric rule', async () => {
    apiMock.GET.mockResolvedValue({
      data: {
        rules: [
          {
            id: 'r1',
            priority: 10,
            match: { from_domain: 'example.com' },
            action: { label: 'must_read' },
          },
          {
            id: 'r2',
            priority: 20,
            match: { subject_contains: 'invoice' },
            action: { label: 'good_to_read' },
          },
        ],
      },
    });
    renderPage();
    await waitFor(() => expect(screen.getByText('must_read')).toBeInTheDocument());
    expect(screen.getByText('good_to_read')).toBeInTheDocument();
    expect(screen.getByText(/priority 10/)).toBeInTheDocument();
    expect(screen.getByText(/from_domain/)).toBeInTheDocument();
  });

  it('renders the empty state when no rules are defined', async () => {
    apiMock.GET.mockResolvedValue({ data: { rules: [] } });
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/no rubric rules defined yet/i)).toBeInTheDocument(),
    );
  });

  it('renders the error state on a failed fetch', async () => {
    apiMock.GET.mockResolvedValue({
      error: { detail: 'rubric outage' },
      response: { status: 500 },
    });
    renderPage();
    await waitFor(() => expect(screen.getByText(/could not load rubric/i)).toBeInTheDocument());
  });
});
