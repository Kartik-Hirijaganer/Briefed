import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type * as ApiClient from '../api/client';
import PreferencesPage from '../pages/settings/PreferencesPage';

const apiMock = vi.hoisted(() => ({ GET: vi.fn(), PATCH: vi.fn() }));

vi.mock('../api/client', async (importOriginal) => {
  const actual = (await importOriginal()) as typeof ApiClient;
  return { ...actual, api: apiMock };
});

vi.mock('../hooks/useOnlineStatus', () => ({ useOnlineStatus: () => true }));

const enqueueMutation = vi.hoisted(() => vi.fn());
vi.mock('../offline/mutations', () => ({ enqueueMutation }));

const renderPage = (): void => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <PreferencesPage />
    </QueryClientProvider>,
  );
};

const basePrefs = {
  auto_execution_enabled: true,
  digest_send_hour_utc: 8,
  redact_pii: false,
  secure_offline_mode: false,
  retention_policy_json: { raw: 30 },
};

describe('<PreferencesPage>', () => {
  beforeEach(() => {
    apiMock.GET.mockReset();
    apiMock.PATCH.mockReset();
    enqueueMutation.mockReset();
  });

  it('renders all three toggles with the current values', async () => {
    apiMock.GET.mockResolvedValue({ data: basePrefs });
    renderPage();
    await waitFor(() =>
      expect(screen.getByLabelText(/automatic daily scans/i)).toBeInTheDocument(),
    );
    expect(screen.getByLabelText(/redact pii/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/enable secure offline mode/i)).toBeInTheDocument();
  });

  it('PATCHes the preferences endpoint when a toggle flips', async () => {
    apiMock.GET.mockResolvedValue({ data: basePrefs });
    apiMock.PATCH.mockResolvedValue({ data: { ...basePrefs, redact_pii: true } });
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(screen.getByLabelText(/redact pii/i)).toBeInTheDocument());
    await user.click(screen.getByLabelText(/redact pii/i));
    await waitFor(() => expect(apiMock.PATCH).toHaveBeenCalled());
    expect(apiMock.PATCH).toHaveBeenCalledWith('/api/v1/preferences', {
      body: { redact_pii: true },
    });
  });

  it('renders the error state on a failed fetch', async () => {
    apiMock.GET.mockResolvedValue({ error: { detail: 'prefs outage' }, response: { status: 500 } });
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/could not load preferences/i)).toBeInTheDocument(),
    );
  });
});
