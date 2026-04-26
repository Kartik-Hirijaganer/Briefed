import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type * as ApiClient from '../api/client';
import SchedulePage from '../pages/settings/SchedulePage';

const apiMock = vi.hoisted(() => ({ GET: vi.fn() }));

vi.mock('../api/client', async (importOriginal) => {
  const actual = (await importOriginal()) as typeof ApiClient;
  return { ...actual, api: apiMock };
});

const renderPage = (): void => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SchedulePage />
    </QueryClientProvider>,
  );
};

describe('<SchedulePage>', () => {
  beforeEach(() => apiMock.GET.mockReset());

  it('renders the digest hour and retention policy from preferences', async () => {
    apiMock.GET.mockResolvedValue({
      data: {
        auto_execution_enabled: true,
        digest_send_hour_utc: 7,
        redact_pii: false,
        secure_offline_mode: false,
        retention_policy_json: { raw: 30, summaries: 365 },
      },
    });
    renderPage();
    await waitFor(() => expect(screen.getByText(/Daily digest/)).toBeInTheDocument());
    expect(screen.getByText(/Sent at 07:00 UTC/)).toBeInTheDocument();
    expect(screen.getByText(/"raw": 30/)).toBeInTheDocument();
  });

  it('shows the error state when the request fails', async () => {
    apiMock.GET.mockResolvedValue({ error: { detail: 'boom' }, response: { status: 500 } });
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/could not load schedule/i)).toBeInTheDocument(),
    );
  });
});
