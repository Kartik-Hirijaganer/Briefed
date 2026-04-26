import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { usePendingMutations } from '../hooks/usePendingMutations';
import type { PendingMutationRecord } from '../offline/db';

const listMock = vi.hoisted(() => vi.fn());

vi.mock('../offline/mutations', () => ({
  listPendingMutations: listMock,
  subscribeToPendingMutations: (listener: () => void): (() => void) => {
    const handler = (): void => listener();
    window.addEventListener('briefed-pending-mutations-changed', handler);
    return () => window.removeEventListener('briefed-pending-mutations-changed', handler);
  },
}));

const sample = (id: string): PendingMutationRecord => ({
  id,
  type: 'preferences_patch',
  payload: { type: 'preferences_patch', body: {} },
  createdAt: 1,
  attempts: 0,
});

describe('usePendingMutations', () => {
  beforeEach(() => listMock.mockReset());
  afterEach(() => vi.restoreAllMocks());

  it('hydrates the list on mount', async () => {
    listMock.mockResolvedValue([sample('a'), sample('b')]);
    const { result } = renderHook(() => usePendingMutations());
    await waitFor(() => expect(result.current.pendingMutations).toHaveLength(2));
  });

  it('refreshes when the change event fires', async () => {
    listMock.mockResolvedValueOnce([sample('a')]);
    const { result } = renderHook(() => usePendingMutations());
    await waitFor(() => expect(result.current.pendingMutations).toHaveLength(1));
    listMock.mockResolvedValueOnce([sample('a'), sample('b')]);
    await act(async () => {
      window.dispatchEvent(new Event('briefed-pending-mutations-changed'));
    });
    await waitFor(() => expect(result.current.pendingMutations).toHaveLength(2));
  });

  it('exposes an explicit refresh callback', async () => {
    listMock.mockResolvedValueOnce([]).mockResolvedValueOnce([sample('a')]);
    const { result } = renderHook(() => usePendingMutations());
    await waitFor(() => expect(result.current.pendingMutations).toHaveLength(0));
    await act(async () => {
      await result.current.refreshPendingMutations();
    });
    expect(result.current.pendingMutations).toHaveLength(1);
  });
});
