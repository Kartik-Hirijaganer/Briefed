import { render } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';

import { Motion } from '@briefed/ui';

/**
 * Phase 8 (plan §19.16): the `<Motion>` helper must respect
 * `prefers-reduced-motion`. We assert the contract by stubbing
 * `matchMedia` to report a reduced-motion preference and verifying the
 * helper invokes that media query. framer-motion caches its
 * `useReducedMotion` MediaQueryList at module scope on first use, so the
 * single combined test below renders `<Motion>` and asserts both the
 * render and the matchMedia call in one shot — splitting them would let
 * the cache absorb the first call and starve the second test of a spy hit.
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

  it('renders and queries prefers-reduced-motion on mount', () => {
    const { getByTestId } = render(
      <Motion data-testid="m" pace="slow" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
        hello
      </Motion>,
    );
    expect(getByTestId('m')).toBeInTheDocument();
    const calls = (window.matchMedia as unknown as { mock: { calls: string[][] } }).mock.calls;
    const queries = calls.map(([q]) => q);
    expect(queries.some((q) => q.includes('prefers-reduced-motion'))).toBe(true);
  });
});
