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

  it('renders the brand glyph and every primary nav target', () => {
    render(
      <MemoryRouter initialEntries={['/app']}>
        <Sidebar />
      </MemoryRouter>,
    );
    expect(screen.getByRole('link', { name: /briefed/i })).toHaveAttribute('href', '/app');
    for (const item of NAV_ITEMS) {
      expect(screen.getByRole('link', { name: new RegExp(item.label, 'i') })).toHaveAttribute(
        'href',
        item.to ? `/app/${item.to}` : '/app',
      );
    }
  });

  it('marks the active route with the accent class', () => {
    render(
      <MemoryRouter initialEntries={['/app/history']}>
        <Sidebar />
      </MemoryRouter>,
    );
    const active = screen.getByRole('link', { name: /history/i });
    expect(active.className).toMatch(/bg-sidebar-active/);
  });

  it('gives every icon-only link a non-empty accessible name and a title tooltip', () => {
    render(
      <MemoryRouter initialEntries={['/app']}>
        <Sidebar />
      </MemoryRouter>,
    );
    const links = screen.getAllByRole('link');
    expect(links.length).toBe(NAV_ITEMS.length + 1); // nav items + brand glyph
    for (const link of links) {
      expect(link).toHaveAccessibleName(/.+/);
      expect(link).toHaveAttribute('title');
      expect(link.getAttribute('title')).not.toBe('');
    }
  });

  it('logs out from the sidebar action', async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={['/app']}>
        <Sidebar />
      </MemoryRouter>,
    );
    await user.click(screen.getByRole('button', { name: /logout/i }));
    expect(logoutMock).toHaveBeenCalledTimes(1);
  });
});
