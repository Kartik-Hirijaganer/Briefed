import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '../api/client';
import { DemoModeProvider } from '../demo/DemoModeProvider';
import { DEMO_RUN_ID } from '../demo/fixtures';
import { MarkReadStatus } from '../features/dashboard/MarkReadStatus';
import type { MarkReadMutation } from '../features/dashboard/useDashboardData';
import DashboardPage from '../pages/DashboardPage';
import HistoryPage from '../pages/HistoryPage';
import HistoryRunDetailPage from '../pages/HistoryRunDetailPage';
import UnsubscribePage from '../pages/UnsubscribePage';
import AccountsPage from '../pages/settings/AccountsPage';
import PreferencesPage from '../pages/settings/PreferencesPage';
import RulesPage from '../pages/settings/RulesPage';
import SchedulePage from '../pages/settings/SchedulePage';
import SettingsLayout from '../pages/settings/SettingsLayout';
import { DemoShell } from '../shell/DemoShell';

vi.mock('../components/AppVersion', () => ({
  AppVersion: () => <span data-testid="app-version">v</span>,
}));

const renderDemoRoute = (initial: string): ReturnType<typeof render> =>
  render(
    <MemoryRouter initialEntries={[initial]}>
      <Routes>
        <Route path="/demo" element={<DemoShell />}>
          <Route index element={<DashboardPage />} />
          <Route path="unsubscribe" element={<UnsubscribePage />} />
          <Route path="history" element={<HistoryPage />} />
          <Route path="history/:runId" element={<HistoryRunDetailPage />} />
          <Route path="settings" element={<SettingsLayout />}>
            <Route path="accounts" element={<AccountsPage />} />
            <Route path="schedule" element={<SchedulePage />} />
            <Route path="rules" element={<RulesPage />} />
            <Route path="preferences" element={<PreferencesPage />} />
          </Route>
        </Route>
      </Routes>
    </MemoryRouter>,
  );

const setLocationPath = (path: string): void => {
  Object.defineProperty(window, 'location', {
    value: {
      ...window.location,
      pathname: path,
      search: '',
      hash: '',
    },
    configurable: true,
  });
};

const renderWithFetchSpy = (path: string) => {
  setLocationPath(path);
  const fetchSpy = vi.spyOn(globalThis, 'fetch');
  renderDemoRoute(path);
  return fetchSpy;
};

const expectNoFetch = async (fetchSpy: { readonly mock: unknown }): Promise<void> => {
  await waitFor(() => expect(fetchSpy).not.toHaveBeenCalled());
};

describe('<DemoShell>', () => {
  const originalLocation = window.location;

  afterEach(() => {
    Object.defineProperty(window, 'location', {
      value: originalLocation,
      configurable: true,
    });
    vi.restoreAllMocks();
  });

  it('renders seeded dashboard data without API fetches or authenticated chrome', async () => {
    const fetchSpy = renderWithFetchSpy('/demo');

    expect(await screen.findByText("Today's Digest")).toBeInTheDocument();
    expect(screen.getByText('Demo data')).toBeInTheDocument();
    expect(screen.getAllByText(/Q3 board deck/i).length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: /start a manual scan/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /disabled in demo/i })).toBeDisabled();
    expect(screen.queryByRole('button', { name: /logout/i })).not.toBeInTheDocument();
    expect(screen.queryByTestId('offline-banners')).not.toBeInTheDocument();
    expect(screen.queryByTestId('queued-actions')).not.toBeInTheDocument();
    await expectNoFetch(fetchSpy);
  });

  it('renders demo unsubscribe data with disabled mutators and no API fetches', async () => {
    const fetchSpy = renderWithFetchSpy('/demo/unsubscribe');

    expect(await screen.findByText('Unsubscribe suggestions')).toBeInTheDocument();
    expect(screen.getByText('deals@promo.example')).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: /select all senders/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /keep selected/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /unsubscribe 0 selected/i })).toBeDisabled();
    expect(screen.getByText('Demo data')).toBeInTheDocument();
    await expectNoFetch(fetchSpy);
  });

  it('renders demo history and run detail data without API fetches', async () => {
    let fetchSpy = renderWithFetchSpy('/demo/history');

    expect(await screen.findByText('Run history')).toBeInTheDocument();
    expect(screen.getByText('scheduled')).toBeInTheDocument();
    expect(screen.getByText('complete')).toBeInTheDocument();
    await expectNoFetch(fetchSpy);

    vi.restoreAllMocks();
    fetchSpy = renderWithFetchSpy(`/demo/history/${DEMO_RUN_ID}`);

    expect(await screen.findByText('Stage timeline')).toBeInTheDocument();
    expect(screen.getByText('Cost breakdown')).toBeInTheDocument();
    expect(screen.getAllByText('New must-read').length).toBeGreaterThan(0);
    await expectNoFetch(fetchSpy);
  });

  it('renders demo settings pages read-only without logout or API fetches', async () => {
    let fetchSpy = renderWithFetchSpy('/demo/settings/accounts');

    expect(await screen.findByText('Gmail accounts')).toBeInTheDocument();
    expect(screen.getByText('Demo Gmail')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /add gmail account/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /more actions/i })).toBeDisabled();
    expect(
      screen.getByRole('button', { name: /disconnect demo@briefeddemo\.com/i }),
    ).toBeDisabled();
    expect(screen.queryByRole('button', { name: /logout/i })).not.toBeInTheDocument();
    await expectNoFetch(fetchSpy);

    vi.restoreAllMocks();
    fetchSpy = renderWithFetchSpy('/demo/settings/schedule');
    expect(await screen.findByText('Automatic scan schedule')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /save schedule/i })).toBeDisabled();
    expect(screen.queryByRole('button', { name: /logout/i })).not.toBeInTheDocument();
    await expectNoFetch(fetchSpy);

    vi.restoreAllMocks();
    fetchSpy = renderWithFetchSpy('/demo/settings/rules');
    expect(await screen.findByText('VIP senders')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: /disabled in demo/i }).length).toBeGreaterThan(0);
    expect(screen.queryByRole('button', { name: /logout/i })).not.toBeInTheDocument();
    await expectNoFetch(fetchSpy);

    vi.restoreAllMocks();
    fetchSpy = renderWithFetchSpy('/demo/settings/preferences');
    expect(await screen.findByLabelText('Automatic daily scans')).toBeDisabled();
    expect(screen.getByLabelText(/redact pii/i)).toBeDisabled();
    expect(screen.getByLabelText(/enable secure offline mode/i)).toBeDisabled();
    expect(screen.queryByRole('button', { name: /logout/i })).not.toBeInTheDocument();
    await expectNoFetch(fetchSpy);
  });

  it('disables the mark-read reconnect action in demo mode', () => {
    const mutation = {
      error: new ApiError('reauthorization required', 403, {
        code: 'gmail_reauthorization_required',
        message: 'Reconnect required.',
        requestId: 'request-1',
      }),
      isError: true,
      data: undefined,
    } as unknown as MarkReadMutation;

    render(
      <DemoModeProvider>
        <MarkReadStatus mutation={mutation} reconnectReturnTo="/demo" />
      </DemoModeProvider>,
    );

    expect(screen.getByRole('button', { name: /disabled in demo/i })).toBeDisabled();
  });
});
