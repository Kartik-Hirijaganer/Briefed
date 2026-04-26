import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ThemeToggle } from '../components/ThemeToggle';

beforeEach(() => {
  window.localStorage.clear();
  document.documentElement.removeAttribute('data-theme');
});

afterEach(() => {
  window.localStorage.clear();
});

describe('<ThemeToggle>', () => {
  it('renders the three preference options', () => {
    render(<ThemeToggle />);
    expect(screen.getByRole('radio', { name: 'System' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Light' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Dark' })).toBeInTheDocument();
  });

  it('selects the persisted preference', () => {
    window.localStorage.setItem('briefed.theme', 'dark');
    render(<ThemeToggle />);
    expect(screen.getByRole('radio', { name: 'Dark' })).toHaveAttribute(
      'aria-checked',
      'true',
    );
  });

  it('cycles to a new preference + persists + invokes onChange', async () => {
    const user = userEvent.setup();
    const handler = vi.fn();
    render(<ThemeToggle onChange={handler} />);
    await user.click(screen.getByRole('radio', { name: 'Dark' }));
    expect(handler).toHaveBeenCalledWith('dark');
    expect(window.localStorage.getItem('briefed.theme')).toBe('dark');
    expect(screen.getByRole('radio', { name: 'Dark' })).toHaveAttribute(
      'aria-checked',
      'true',
    );
  });
});
