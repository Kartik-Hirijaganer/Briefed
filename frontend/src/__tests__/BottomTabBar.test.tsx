import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import { BottomTabBar } from '../shell/BottomTabBar';

describe('<BottomTabBar>', () => {
  it('renders only the three mobile-flagged tabs', () => {
    render(
      <MemoryRouter initialEntries={['/app']}>
        <BottomTabBar />
      </MemoryRouter>,
    );
    const nav = screen.getByRole('navigation', { name: /primary mobile/i });
    const links = within(nav).getAllByRole('link');
    expect(links).toHaveLength(3);
    expect(links.map((a) => a.getAttribute('href'))).toEqual([
      '/app',
      '/app/history',
      '/app/settings/accounts',
    ]);
  });

  it('highlights the active tab', () => {
    render(
      <MemoryRouter initialEntries={['/app/history']}>
        <BottomTabBar />
      </MemoryRouter>,
    );
    expect(screen.getByRole('link', { name: /history/i }).className).toMatch(/text-accent/);
  });
});
