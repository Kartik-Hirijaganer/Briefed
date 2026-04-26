import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import SettingsLayout from '../pages/settings/SettingsLayout';

const renderAt = (path: string): void => {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/settings" element={<SettingsLayout />}>
          <Route path="accounts" element={<div data-testid="child">accounts</div>} />
          <Route path="preferences" element={<div data-testid="child">prefs</div>} />
          <Route path="prompts" element={<div data-testid="child">prompts</div>} />
          <Route path="schedule" element={<div data-testid="child">schedule</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
};

describe('<SettingsLayout>', () => {
  it('renders the four section tabs and active link', () => {
    renderAt('/settings/accounts');
    expect(screen.getByRole('heading', { level: 1, name: /settings/i })).toBeInTheDocument();
    for (const label of ['Accounts', 'Preferences', 'Prompts', 'Schedule']) {
      expect(screen.getByRole('link', { name: label })).toBeInTheDocument();
    }
    expect(screen.getByRole('link', { name: 'Accounts' }).className).toMatch(/border-accent/);
  });

  it('renders the matched child outlet', () => {
    renderAt('/settings/preferences');
    expect(screen.getByTestId('child')).toHaveTextContent('prefs');
  });
});
