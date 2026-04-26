import { useEffect, useState } from 'react';

/**
 * Coarse breakpoint tier. Keep this in sync with Tailwind — `sm` < 640,
 * `md` < 1024, `lg` ≥ 1024.
 */
export type Breakpoint = 'sm' | 'md' | 'lg';

const resolveBreakpoint = (width: number): Breakpoint => {
  if (width >= 1024) return 'lg';
  if (width >= 640) return 'md';
  return 'sm';
};

/**
 * Reactive viewport tier. Used by `<AppShell>` to pick sidebar vs.
 * bottom-tab navigation per plan §10.
 *
 * @returns Current breakpoint, updated on resize.
 */
export function useBreakpoint(): Breakpoint {
  const [breakpoint, setBreakpoint] = useState<Breakpoint>(() =>
    typeof window === 'undefined' ? 'lg' : resolveBreakpoint(window.innerWidth),
  );
  useEffect(() => {
    const handler = (): void => setBreakpoint(resolveBreakpoint(window.innerWidth));
    window.addEventListener('resize', handler);
    return () => window.removeEventListener('resize', handler);
  }, []);
  return breakpoint;
}
