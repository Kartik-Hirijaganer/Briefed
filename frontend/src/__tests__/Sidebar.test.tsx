import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { Sidebar } from '../shell/Sidebar';
import { NAV_ITEMS } from '../shell/navItems';

const logoutMock = vi.hoisted(() => vi.fn());

vi.mock('../api/session', () => ({
  logoutAndClearBrowserSession: logoutMock,
}));

describe('<Sidebar>', () => {
  beforeEach(() => {
    logoutMock.mockReset();
    logoutMock.mockResolvedValue(undefined);
  });

  it('renders the brand and every primary nav target', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <Sidebar />
      </MemoryRouter>,
    );
    expect(screen.getByText('Briefed')).toBeInTheDocument();
    for (const item of NAV_ITEMS) {
      expect(screen.getByRole('link', { name: new RegExp(item.label, 'i') })).toHaveAttribute(
        'href',
        item.to,
      );
    }
  });

  it('marks the active route with the accent class', () => {
    render(
      <MemoryRouter initialEntries={['/history']}>
        <Sidebar />
      </MemoryRouter>,
    );
    const active = screen.getByRole('link', { name: /history/i });
    expect(active.className).toMatch(/bg-sidebar-active/);
  });

  it('logs out from the sidebar action', async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={['/']}>
        <Sidebar />
      </MemoryRouter>,
    );
    await user.click(screen.getByRole('button', { name: /logout/i }));
    expect(logoutMock).toHaveBeenCalledTimes(1);
  });
});
