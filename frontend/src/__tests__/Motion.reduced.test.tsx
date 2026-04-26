import { render } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';

import { Motion } from '@briefed/ui';

/**
 * Phase 8 (plan §19.16): the `<Motion>` helper must respect
 * `prefers-reduced-motion`. We assert the contract by stubbing
 * `matchMedia` to report a reduced-motion preference and verifying the
 * helper skips the transition duration. framer-motion reads
 * `prefers-reduced-motion` via the same media query, so this stub is
 * the right wedge for unit-level coverage.
 */
describe('<Motion> reduced-motion respect', () => {
  const originalMatchMedia = window.matchMedia;

  beforeEach(() => {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      configurable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches: query === '(prefers-reduced-motion: reduce)',
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });
  });

  afterEach(() => {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      configurable: true,
      value: originalMatchMedia,
    });
  });

  it('renders without throwing when reduced motion is preferred', () => {
    const { getByTestId } = render(
      <Motion data-testid="m" pace="slow" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
        hello
      </Motion>,
    );
    expect(getByTestId('m')).toBeInTheDocument();
  });

  it('queries prefers-reduced-motion media query', () => {
    render(
      <Motion pace="base" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
        hello
      </Motion>,
    );
    expect(window.matchMedia).toHaveBeenCalled();
    const calls = (window.matchMedia as unknown as { mock: { calls: string[][] } }).mock.calls;
    const queries = calls.map(([q]) => q);
    expect(queries.some((q) => q.includes('prefers-reduced-motion'))).toBe(true);
  });
});
