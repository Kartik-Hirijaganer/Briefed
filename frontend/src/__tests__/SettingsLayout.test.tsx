import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import SettingsLayout from '../pages/settings/SettingsLayout';

const logoutMock = vi.hoisted(() => vi.fn());

vi.mock('../api/session', () => ({
  logoutAndClearBrowserSession: logoutMock,
}));

const renderAt = (path: string): void => {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/settings" element={<SettingsLayout />}>
          <Route path="accounts" element={<div data-testid="child">accounts</div>} />
          <Route path="schedule" element={<div data-testid="child">schedule</div>} />
          <Route path="rules" element={<div data-testid="child">rules</div>} />
          <Route path="preferences" element={<div data-testid="child">prefs</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
};

describe('<SettingsLayout>', () => {
  beforeEach(() => {
    logoutMock.mockReset();
    logoutMock.mockResolvedValue(undefined);
  });

  it('renders the four section tabs and active link', () => {
    renderAt('/settings/accounts');
    expect(screen.getByRole('heading', { level: 1, name: /settings/i })).toBeInTheDocument();
    for (const label of ['Accounts', 'Schedule', 'Rules', 'Preferences']) {
      expect(screen.getByRole('link', { name: label })).toBeInTheDocument();
    }
    expect(screen.getByRole('link', { name: 'Accounts' }).className).toMatch(/border-accent/);
  });

  it('renders the matched child outlet', () => {
    renderAt('/settings/preferences');
    expect(screen.getByTestId('child')).toHaveTextContent('prefs');
  });

  it('logs out from the settings header action', async () => {
    const user = userEvent.setup();
    renderAt('/settings/accounts');
    await user.click(screen.getByRole('button', { name: /logout/i }));
    expect(logoutMock).toHaveBeenCalledTimes(1);
  });
});
