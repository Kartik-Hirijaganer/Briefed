import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import { Sidebar } from '../shell/Sidebar';
import { NAV_ITEMS } from '../shell/navItems';

describe('<Sidebar>', () => {
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
      <MemoryRouter initialEntries={['/jobs']}>
        <Sidebar />
      </MemoryRouter>,
    );
    const active = screen.getByRole('link', { name: /jobs/i });
    expect(active.className).toMatch(/text-accent/);
  });
});
