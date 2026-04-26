import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import { BottomTabBar } from '../shell/BottomTabBar';

describe('<BottomTabBar>', () => {
  it('renders only the four mobile-flagged tabs', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <BottomTabBar />
      </MemoryRouter>,
    );
    const nav = screen.getByRole('navigation', { name: /primary mobile/i });
    const links = within(nav).getAllByRole('link');
    expect(links).toHaveLength(4);
    expect(links.map((a) => a.getAttribute('href'))).toEqual([
      '/',
      '/must-read',
      '/jobs',
      '/settings/accounts',
    ]);
  });

  it('highlights the active tab', () => {
    render(
      <MemoryRouter initialEntries={['/must-read']}>
        <BottomTabBar />
      </MemoryRouter>,
    );
    expect(screen.getByRole('link', { name: /must read/i }).className).toMatch(/text-accent/);
  });
});
