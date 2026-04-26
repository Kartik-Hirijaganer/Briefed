import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type * as ApiClient from '../api/client';
import TriagePage from '../pages/TriagePage';

const apiMock = vi.hoisted(() => ({ GET: vi.fn() }));

vi.mock('../api/client', async (importOriginal) => {
  const actual = (await importOriginal()) as typeof ApiClient;
  return { ...actual, api: apiMock };
});

vi.mock('../hooks/useFreshnessState', () => ({
  useFreshnessState: () => ({ state: 'fresh', lastKnownGoodAt: null }),
}));

vi.mock('../features/email/useEmailBucketMutation', () => ({
  useEmailBucketMutation: () => ({ mutate: vi.fn() }),
}));

vi.mock('../features/email/EmailCard', () => ({
  EmailCard: ({ email }: { email: { id: string; subject: string } }) => (
    <div data-testid={`email-${email.id}`}>{email.subject}</div>
  ),
}));

const renderPage = (bucket: 'must_read' | 'good_to_read' | 'ignore' | 'waste'): void => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TriagePage bucket={bucket} />
    </QueryClientProvider>,
  );
};

describe('<TriagePage>', () => {
  beforeEach(() => apiMock.GET.mockReset());

  it('renders the bucket label and email rows', async () => {
    apiMock.GET.mockResolvedValue({
      data: {
        emails: [
          { id: 'e1', subject: 'meeting tomorrow' },
          { id: 'e2', subject: 'invoice due' },
        ],
        total: 2,
      },
    });
    renderPage('must_read');
    expect(screen.getByText('Must read')).toBeInTheDocument();
    expect(await screen.findByTestId('email-e1')).toHaveTextContent('meeting tomorrow');
    expect(screen.getByTestId('email-e2')).toBeInTheDocument();
    expect(screen.getByText('2 total')).toBeInTheDocument();
    expect(apiMock.GET).toHaveBeenCalledWith('/api/v1/emails', {
      params: { query: { bucket: 'must_read', limit: 50 } },
    });
  });

  it('renders the empty state when no emails for bucket', async () => {
    apiMock.GET.mockResolvedValue({ data: { emails: [], total: 0 } });
    renderPage('waste');
    await waitFor(() => expect(screen.getByText('Nothing in Waste')).toBeInTheDocument());
  });

  it('renders the error state on a failed fetch', async () => {
    apiMock.GET.mockResolvedValue({ error: { detail: 'down' }, response: { status: 500 } });
    renderPage('good_to_read');
    await waitFor(() => expect(screen.getByText(/could not load emails/i)).toBeInTheDocument());
  });
});
