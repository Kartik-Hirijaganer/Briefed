import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ProfileSettings } from '../features/settings/ProfileSettings';

import type { UserProfile, UserSchedule } from '../features/settings/profileApi';

const baseProfile: UserProfile = {
  display_name: 'Alex',
  email_aliases: [],
  redaction_aliases: [],
  presidio_enabled: true,
  theme_preference: 'system',
  schedule_frequency: 'once_daily',
  schedule_times_local: ['08:00'],
  schedule_timezone: 'UTC',
};

const baseSchedule: UserSchedule = {
  schedule_frequency: 'once_daily',
  schedule_times_local: ['08:00'],
  schedule_timezone: 'UTC',
  next_run_at_utc: '2026-04-26T08:00:00+00:00',
};

vi.mock('../features/settings/profileApi', () => ({
  fetchProfile: vi.fn(async () => baseProfile),
  fetchSchedule: vi.fn(async () => baseSchedule),
  patchProfile: vi.fn(async (body) => ({ ...baseProfile, ...body })),
  patchSchedule: vi.fn(async (body) => ({ ...baseSchedule, ...body })),
}));

function wrap(node: ReactNode): JSX.Element {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{node}</QueryClientProvider>;
}

beforeEach(() => {
  window.localStorage.clear();
  document.documentElement.removeAttribute('data-theme');
});

afterEach(() => {
  window.localStorage.clear();
});

describe('<ProfileSettings>', () => {
  it('renders the four Track C panels once data resolves', async () => {
    render(wrap(<ProfileSettings />));
    expect(await screen.findByText('Profile')).toBeInTheDocument();
    expect(screen.getByText('Schedule')).toBeInTheDocument();
    expect(screen.getByText('Appearance')).toBeInTheDocument();
    expect(screen.getByText('Privacy')).toBeInTheDocument();
  });

  it('updates the display name on blur', async () => {
    const user = userEvent.setup();
    const profileApi = await import('../features/settings/profileApi');
    render(wrap(<ProfileSettings />));
    const input = await screen.findByLabelText(/Display name/);
    await user.clear(input);
    await user.type(input, 'New Name');
    await user.tab();
    await waitFor(() => {
      const calls = vi.mocked(profileApi.patchProfile).mock.calls;
      expect(calls.length).toBeGreaterThan(0);
      const last = calls[calls.length - 1]![0];
      expect(last).toMatchObject({ display_name: 'New Name' });
    });
  });

  it('persists a cadence change through the schedule mutation', async () => {
    const user = userEvent.setup();
    const profileApi = await import('../features/settings/profileApi');
    render(wrap(<ProfileSettings />));
    const twiceDaily = await screen.findByLabelText('Twice a day');
    await user.click(twiceDaily);
    await waitFor(() => {
      const calls = vi.mocked(profileApi.patchSchedule).mock.calls;
      expect(calls.length).toBeGreaterThan(0);
      const last = calls[calls.length - 1]![0];
      expect(last).toMatchObject({
        schedule_frequency: 'twice_daily',
        schedule_times_local: ['08:00', '18:00'],
      });
    });
  });

  it('forwards a theme change through the profile mutation', async () => {
    const user = userEvent.setup();
    const profileApi = await import('../features/settings/profileApi');
    render(wrap(<ProfileSettings />));
    const darkOption = await screen.findByRole('radio', { name: 'Dark' });
    await user.click(darkOption);
    await waitFor(() => {
      const calls = vi.mocked(profileApi.patchProfile).mock.calls;
      const last = calls[calls.length - 1]?.[0];
      expect(last).toMatchObject({ theme_preference: 'dark' });
    });
  });
});
