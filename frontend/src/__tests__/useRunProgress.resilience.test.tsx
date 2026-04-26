import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import { useRunProgress } from '../hooks/useRunProgress';
import { api } from '../api/client';

/**
 * Phase 8 polling-resilience drill (plan §19.16 + §20.5 polling-only):
 * the manual-run hook must keep polling on transient failures and stop
 * once the run reaches a terminal state — the SSE-equivalent reconnection
 * test the plan calls for, applied to TanStack Query polling.
 */
describe('useRunProgress polling resilience', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  function renderWithClient(runId: string | null): {
    result: { current: ReturnType<typeof useRunProgress> };
    client: QueryClient;
    rerender: (id: string | null) => void;
  } {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result, rerender } = renderHook(({ id }) => useRunProgress(id), {
      wrapper,
      initialProps: { id: runId },
    });
    return {
      result,
      client,
      rerender: (id) => rerender({ id }),
    };
  }

  it('keeps polling after a transient fetch error', async () => {
    let calls = 0;
    const spy = vi.spyOn(api, 'GET').mockImplementation(async () => {
      calls += 1;
      if (calls === 1) {
        return {
          data: undefined,
          error: { message: 'transient', code: 503 } as unknown,
          response: new Response('boom', { status: 503 }),
        } as unknown as ReturnType<typeof api.GET>;
      }
      return {
        data: { id: 'r-1', status: 'running', stages: [] },
        error: undefined,
        response: new Response(),
      } as unknown as ReturnType<typeof api.GET>;
    });

    const { result } = renderWithClient('r-1');

    await waitFor(
      () => {
        expect(spy).toHaveBeenCalled();
      },
      { timeout: 1000 },
    );
    // The hook eventually sees a successful status because the second
    // poll succeeds.
    await waitFor(
      () => {
        expect(result.current.status?.status).toBe('running');
      },
      { timeout: 5000 },
    );
  });

  it('stops polling once the run reaches a terminal state', async () => {
    const spy = vi.spyOn(api, 'GET').mockResolvedValue({
      data: { id: 'r-1', status: 'complete', stages: [] },
      error: undefined,
      response: new Response(),
    } as unknown as ReturnType<typeof api.GET>);

    const { result } = renderWithClient('r-1');

    await waitFor(
      () => {
        expect(result.current.status?.status).toBe('complete');
      },
      { timeout: 5000 },
    );
    const before = spy.mock.calls.length;
    await act(async () => {
      await new Promise((r) => setTimeout(r, 200));
    });
    // Polling must not continue once a terminal status is reported.
    expect(spy.mock.calls.length).toBe(before);
  });
});
