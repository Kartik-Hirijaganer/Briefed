import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it } from 'vitest';

import { useFreshnessState } from '../hooks/useFreshnessState';

const setOnline = (value: boolean): void => {
  Object.defineProperty(window.navigator, 'onLine', {
    value,
    configurable: true,
  });
};

const wrap =
  (client: QueryClient) =>
  ({ children }: { children: ReactNode }): JSX.Element => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );

const STALE_MS = 60_000;

describe('useFreshnessState', () => {
  afterEach(() => setOnline(true));

  it('returns "offline" when the browser is offline', () => {
    setOnline(false);
    const client = new QueryClient();
    const { result } = renderHook(
      () => useFreshnessState({ queryKey: ['k'], staleTime: STALE_MS }),
      { wrapper: wrap(client) },
    );
    expect(result.current.state).toBe('offline');
  });

  it('returns "fresh" for a recent successful fetch', () => {
    setOnline(true);
    const client = new QueryClient();
    client.setQueryData(['k'], { ok: true });
    const { result } = renderHook(
      () => useFreshnessState({ queryKey: ['k'], staleTime: STALE_MS }),
      { wrapper: wrap(client) },
    );
    expect(result.current.state).toBe('fresh');
    expect(result.current.lastKnownGoodAt).not.toBeNull();
  });

  it('returns "stale" when the data is older than staleTime', () => {
    setOnline(true);
    const client = new QueryClient();
    client.setQueryData(['k'], { ok: true });
    const queryState = client.getQueryState(['k']);
    if (queryState) {
      Object.defineProperty(queryState, 'dataUpdatedAt', {
        value: Date.now() - STALE_MS - 1000,
        configurable: true,
      });
    }
    const { result } = renderHook(
      () => useFreshnessState({ queryKey: ['k'], staleTime: STALE_MS }),
      { wrapper: wrap(client) },
    );
    expect(result.current.state).toBe('stale');
  });

  it('returns "sync_failed" when the query has a failure count and has not been invalidated', () => {
    setOnline(true);
    const client = new QueryClient();
    const cache = client.getQueryCache();
    const query = cache.build(client, { queryKey: ['k'], queryFn: async () => null });
    Object.defineProperty(query.state, 'fetchFailureCount', { value: 2, configurable: true });
    Object.defineProperty(query.state, 'isInvalidated', { value: false, configurable: true });
    const { result } = renderHook(
      () => useFreshnessState({ queryKey: ['k'], staleTime: STALE_MS }),
      { wrapper: wrap(client) },
    );
    expect(result.current.state).toBe('sync_failed');
  });
});
