import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useSyncQueueDrain } from '../hooks/useSyncQueueDrain';

const replayMock = vi.hoisted(() => vi.fn());
vi.mock('../offline/mutations', () => ({ replayPendingMutations: replayMock }));

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

describe('useSyncQueueDrain', () => {
  beforeEach(() => {
    replayMock.mockReset();
    setOnline(true);
  });

  afterEach(() => {
    setOnline(true);
    vi.restoreAllMocks();
  });

  it('drains automatically on mount when online', async () => {
    replayMock.mockResolvedValue({ replayed: 0, failed: 0 });
    const client = new QueryClient();
    renderHook(() => useSyncQueueDrain(), { wrapper: wrap(client) });
    await waitFor(() => expect(replayMock).toHaveBeenCalled());
  });

  it('reports a friendly error when partial replay fails', async () => {
    replayMock.mockResolvedValue({ replayed: 0, failed: 2 });
    const client = new QueryClient();
    const { result } = renderHook(() => useSyncQueueDrain(), { wrapper: wrap(client) });
    await waitFor(() =>
      expect(result.current.lastReplayError).toBe('Some queued actions could not sync.'),
    );
  });

  it('captures the thrown error message', async () => {
    replayMock.mockRejectedValue(new Error('catastrophic'));
    const client = new QueryClient();
    const { result } = renderHook(() => useSyncQueueDrain(), { wrapper: wrap(client) });
    await waitFor(() => expect(result.current.lastReplayError).toBe('catastrophic'));
  });

  it('skips replay while offline', async () => {
    setOnline(false);
    const client = new QueryClient();
    const { result } = renderHook(() => useSyncQueueDrain(), { wrapper: wrap(client) });
    await act(async () => {
      await result.current.drainNow();
    });
    expect(replayMock).not.toHaveBeenCalled();
  });
});
