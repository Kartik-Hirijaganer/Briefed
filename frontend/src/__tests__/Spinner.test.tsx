import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { Spinner } from '@briefed/ui';

describe('<Spinner>', () => {
  it('renders a status role with the icon spinning', () => {
    render(<Spinner />);
    const status = screen.getByRole('status');
    const svg = status.querySelector('svg');
    expect(svg).not.toBeNull();
    expect(svg?.getAttribute('class')).toMatch(/animate-spin/);
  });

  it('pauses the spin under prefers-reduced-motion', () => {
    render(<Spinner />);
    const svg = screen.getByRole('status').querySelector('svg');
    expect(svg?.getAttribute('class')).toMatch(/motion-reduce:animate-none/);
  });

  it('announces an sr-only label inside the live region when provided', () => {
    render(<Spinner label="Loading senders" />);
    const label = screen.getByText('Loading senders');
    expect(label).toHaveClass('sr-only');
    expect(screen.getByRole('status')).toContainElement(label);
  });

  it('adds no text content when no label is given (no accessible-name pollution)', () => {
    render(<Spinner />);
    expect(screen.getByRole('status').textContent).toBe('');
  });
});
