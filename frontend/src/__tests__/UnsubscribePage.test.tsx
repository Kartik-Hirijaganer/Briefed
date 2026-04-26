import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type * as ApiClient from '../api/client';
import UnsubscribePage from '../pages/UnsubscribePage';

const apiMock = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }));

vi.mock('../api/client', async (importOriginal) => {
  const actual = (await importOriginal()) as typeof ApiClient;
  return { ...actual, api: apiMock };
});

vi.mock('../hooks/useFreshnessState', () => ({
  useFreshnessState: () => ({ state: 'fresh', lastKnownGoodAt: null }),
}));

vi.mock('../hooks/useOnlineStatus', () => ({ useOnlineStatus: () => true }));
vi.mock('../offline/mutations', () => ({ enqueueMutation: vi.fn() }));

const renderPage = (): void => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <UnsubscribePage />
    </QueryClientProvider>,
  );
};

const suggestion = (overrides: Partial<Record<string, unknown>> = {}): Record<string, unknown> => ({
  id: 's1',
  sender_email: 'noisy@news.example',
  sender_domain: 'news.example',
  confidence: 0.91,
  rationale: 'opened 0/30',
  list_unsubscribe: { http_urls: ['https://news.example/unsub'] },
  ...overrides,
});

describe('<UnsubscribePage>', () => {
  beforeEach(() => {
    apiMock.GET.mockReset();
    apiMock.POST.mockReset();
  });

  it('renders one card per suggestion with score and unsubscribe link', async () => {
    apiMock.GET.mockResolvedValue({ data: { suggestions: [suggestion()] } });
    renderPage();
    await waitFor(() => expect(screen.getByText('noisy@news.example')).toBeInTheDocument());
    expect(screen.getByText('score 0.91')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /open unsubscribe link/i })).toHaveAttribute(
      'href',
      'https://news.example/unsub',
    );
  });

  it('POSTs the dismiss endpoint when "Keep" is clicked', async () => {
    apiMock.GET.mockResolvedValue({ data: { suggestions: [suggestion()] } });
    apiMock.POST.mockResolvedValue({ data: undefined });
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(screen.getByText('noisy@news.example')).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /keep/i }));
    await waitFor(() => expect(apiMock.POST).toHaveBeenCalled());
    expect(apiMock.POST).toHaveBeenCalledWith(
      '/api/v1/unsubscribes/{suggestion_id}/dismiss',
      { params: { path: { suggestion_id: 's1' } } },
    );
  });

  it('POSTs the confirm endpoint when "Mark unsubscribed" is clicked', async () => {
    apiMock.GET.mockResolvedValue({ data: { suggestions: [suggestion()] } });
    apiMock.POST.mockResolvedValue({ data: undefined });
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(screen.getByText('noisy@news.example')).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /mark unsubscribed/i }));
    await waitFor(() => expect(apiMock.POST).toHaveBeenCalled());
    expect(apiMock.POST).toHaveBeenCalledWith(
      '/api/v1/unsubscribes/{suggestion_id}/confirm',
      { params: { path: { suggestion_id: 's1' } } },
    );
  });

  it('renders the empty state when no suggestions', async () => {
    apiMock.GET.mockResolvedValue({ data: { suggestions: [] } });
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/no suggestions right now/i)).toBeInTheDocument(),
    );
  });

  it('renders the error state on a failed fetch', async () => {
    apiMock.GET.mockResolvedValue({ error: { detail: 'down' }, response: { status: 500 } });
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/could not load suggestions/i)).toBeInTheDocument(),
    );
  });
});
