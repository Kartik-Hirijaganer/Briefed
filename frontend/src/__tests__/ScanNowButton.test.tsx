import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type * as ApiClient from '../api/client';
import { ScanNowButton } from '../features/dashboard/ScanNowButton';

const apiMock = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }));
const breakpointMock = vi.hoisted(() => ({ value: 'lg' as 'sm' | 'md' | 'lg' }));
const onlineMock = vi.hoisted(() => ({ value: true }));
const runProgressMock = vi.hoisted(() => ({
  status: null as { status: string; stats?: Record<string, number> } | null,
}));

vi.mock('../api/client', async (importOriginal) => {
  const actual = (await importOriginal()) as typeof ApiClient;
  return { ...actual, api: apiMock };
});
vi.mock('../hooks/useOnlineStatus', () => ({ useOnlineStatus: () => onlineMock.value }));
vi.mock('../hooks/useBreakpoint', () => ({ useBreakpoint: () => breakpointMock.value }));
vi.mock('../hooks/useRunProgress', () => ({
  useRunProgress: () => ({ status: runProgressMock.status }),
}));

const renderButton = (): void => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ScanNowButton />
      </MemoryRouter>
    </QueryClientProvider>,
  );
};

describe('<ScanNowButton>', () => {
  beforeEach(() => {
    apiMock.GET.mockReset();
    apiMock.POST.mockReset();
    runProgressMock.status = null;
    onlineMock.value = true;
    breakpointMock.value = 'lg';
    apiMock.GET.mockResolvedValue({ data: { accounts: [{ id: 'a1', email: 'me@example.com' }] } });
  });

  it('renders the desktop scan button by default', async () => {
    renderButton();
    expect(await screen.findByRole('button', { name: /start a manual scan/i })).toBeInTheDocument();
    expect(screen.getByText(/scan now/i)).toBeInTheDocument();
  });

  it('disables the button when offline', async () => {
    onlineMock.value = false;
    renderButton();
    const button = await screen.findByRole('button', { name: /start a manual scan/i });
    expect(button).toBeDisabled();
  });

  it('POSTs /api/v1/runs when clicked', async () => {
    apiMock.POST.mockResolvedValue({ data: { run_id: 'r1' } });
    const user = userEvent.setup();
    renderButton();
    await user.click(await screen.findByRole('button', { name: /start a manual scan/i }));
    await waitFor(() => expect(apiMock.POST).toHaveBeenCalled());
    expect(apiMock.POST).toHaveBeenCalledWith('/api/v1/runs', { body: { kind: 'manual' } });
  });

  it('shows the error label when the start mutation fails', async () => {
    apiMock.POST.mockResolvedValue({ error: { detail: 'rate limit' }, response: { status: 429 } });
    const user = userEvent.setup();
    renderButton();
    await user.click(await screen.findByRole('button', { name: /start a manual scan/i }));
    await waitFor(() => expect(screen.getByText(/retry/i)).toBeInTheDocument());
  });

  it('renders the mobile pinned card variant', async () => {
    breakpointMock.value = 'sm';
    renderButton();
    expect(await screen.findByText(/1 account/)).toBeInTheDocument();
  });

  it('triggers a scan when the SCAN_NOW_EVENT fires', async () => {
    apiMock.POST.mockResolvedValue({ data: { run_id: 'r2' } });
    renderButton();
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /start a manual scan/i })).toBeInTheDocument(),
    );
    await act(async () => {
      window.dispatchEvent(new Event('briefed-scan-now'));
    });
    await waitFor(() => expect(apiMock.POST).toHaveBeenCalled());
  });
});
