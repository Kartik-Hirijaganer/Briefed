import { renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it } from 'vitest';

import { RouteBaseProvider, type RouteBase, useAppPath } from '../routing/routeBase';

const wrapperFor =
  (base: RouteBase) =>
  ({ children }: { readonly children: ReactNode }): JSX.Element => (
    <RouteBaseProvider base={base}>{children}</RouteBaseProvider>
  );

describe('useAppPath', () => {
  it('builds /app paths for app routes', () => {
    const { result } = renderHook(() => useAppPath(), { wrapper: wrapperFor('/app') });
    expect(result.current('')).toBe('/app');
    expect(result.current('history')).toBe('/app/history');
    expect(result.current('?bucket=must_read')).toBe('/app?bucket=must_read');
  });

  it('builds /demo paths for demo routes', () => {
    const { result } = renderHook(() => useAppPath(), { wrapper: wrapperFor('/demo') });
    expect(result.current('')).toBe('/demo');
    expect(result.current('history')).toBe('/demo/history');
    expect(result.current('?bucket=must_read')).toBe('/demo?bucket=must_read');
  });
});
