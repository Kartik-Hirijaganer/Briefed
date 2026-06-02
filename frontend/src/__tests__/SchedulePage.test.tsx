import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type * as ApiClient from '../api/client';
import SchedulePage from '../pages/settings/SchedulePage';

const apiMock = vi.hoisted(() => ({ GET: vi.fn(), PATCH: vi.fn() }));

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
  beforeEach(() => {
    apiMock.GET.mockReset();
    apiMock.PATCH.mockReset();
  });

  it('renders the profile schedule form from /profile/me/schedule', async () => {
    apiMock.GET.mockResolvedValue({
      data: {
        schedule_frequency: 'once_daily',
        schedule_times_local: ['08:00'],
        schedule_timezone: 'UTC',
        next_run_at_utc: '2026-05-31T08:00:00Z',
      },
    });
    renderPage();

    expect(await screen.findByText(/automatic scan schedule/i)).toBeInTheDocument();
    expect(apiMock.GET).toHaveBeenCalledWith('/api/v1/profile/me/schedule');
    expect(screen.getByLabelText('Once a day')).toBeChecked();
    expect(screen.getByDisplayValue('08:00')).toBeInTheDocument();
  });

  it('writes cadence and slots to /profile/me/schedule', async () => {
    const user = userEvent.setup();
    apiMock.GET.mockResolvedValue({
      data: {
        schedule_frequency: 'once_daily',
        schedule_times_local: ['08:00'],
        schedule_timezone: 'UTC',
        next_run_at_utc: '2026-05-31T08:00:00Z',
      },
    });
    apiMock.PATCH.mockResolvedValue({
      data: {
        schedule_frequency: 'twice_daily',
        schedule_times_local: ['08:00', '18:00'],
        schedule_timezone: 'UTC',
        next_run_at_utc: '2026-05-31T18:00:00Z',
      },
    });
    renderPage();

    await user.click(await screen.findByLabelText('Twice a day'));
    await waitFor(() => expect(apiMock.PATCH).toHaveBeenCalled());
    expect(apiMock.PATCH).toHaveBeenCalledWith('/api/v1/profile/me/schedule', {
      body: {
        schedule_frequency: 'twice_daily',
        schedule_times_local: ['08:00', '18:00'],
      },
    });
  });

  it('shows the error state when the request fails', async () => {
    apiMock.GET.mockResolvedValue({ error: { detail: 'boom' }, response: { status: 500 } });
    renderPage();
    await waitFor(() => expect(screen.getByText(/could not load schedule/i)).toBeInTheDocument());
  });

  it('limits the timezone dropdown to US and India zones', async () => {
    apiMock.GET.mockResolvedValue({
      data: {
        schedule_frequency: 'once_daily',
        schedule_times_local: ['08:00'],
        schedule_timezone: 'America/New_York',
        next_run_at_utc: '2026-06-01T12:00:00Z',
      },
    });
    renderPage();

    await screen.findByText(/automatic scan schedule/i);
    const values = within(screen.getByRole('combobox'))
      .getAllByRole('option')
      .map((option) => (option as HTMLOptionElement).value);
    expect(values).toEqual([
      'America/New_York',
      'America/Chicago',
      'America/Denver',
      'America/Phoenix',
      'America/Los_Angeles',
      'America/Anchorage',
      'Pacific/Honolulu',
      'Asia/Kolkata',
    ]);
  });

  it('keeps a legacy stored zone selectable outside the US/India set', async () => {
    apiMock.GET.mockResolvedValue({
      data: {
        schedule_frequency: 'once_daily',
        schedule_times_local: ['08:00'],
        schedule_timezone: 'Europe/London',
        next_run_at_utc: '2026-06-01T12:00:00Z',
      },
    });
    renderPage();

    await screen.findByText(/automatic scan schedule/i);
    const select = screen.getByRole('combobox') as HTMLSelectElement;
    const values = within(select)
      .getAllByRole('option')
      .map((option) => (option as HTMLOptionElement).value);
    expect(values[0]).toBe('Europe/London');
    expect(values).toContain('Asia/Kolkata');
    expect(select.value).toBe('Europe/London');
  });
});
