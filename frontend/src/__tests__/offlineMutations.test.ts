import { QueryClient } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  enqueueMutation,
  listPendingMutations,
  removePendingMutation,
  replayPendingMutations,
} from '../offline/mutations';
import type { PendingMutationRecord } from '../offline/db';

const dbMock = vi.hoisted(() => {
  interface Row {
    readonly id: string;
    [key: string]: unknown;
  }
  const rows: Row[] = [];
  const pendingMutations = {
    rows,
    async add(row: Row) {
      rows.push(row);
      return row.id;
    },
    async delete(id: string) {
      const idx = rows.findIndex((row) => row.id === id);
      if (idx >= 0) rows.splice(idx, 1);
    },
    async update(id: string, patch: Partial<Row>) {
      const idx = rows.findIndex((row) => row.id === id);
      if (idx < 0) return 0;
      rows[idx] = { ...rows[idx], ...patch };
      return 1;
    },
    async get(id: string) {
      return rows.find((row) => row.id === id);
    },
    orderBy(key: string) {
      return {
        async toArray() {
          return [...rows].sort((a, b) => {
            const av = a[key] as number;
            const bv = b[key] as number;
            return av - bv;
          });
        },
      };
    },
  };
  return { offlineDb: { pendingMutations }, rows };
});

vi.mock('../offline/db', () => ({
  offlineDb: dbMock.offlineDb,
}));

const apiMock = vi.hoisted(() => ({
  GET: vi.fn(),
  POST: vi.fn(),
  PATCH: vi.fn(),
  DELETE: vi.fn(),
}));

vi.mock('../api/client', () => ({
  api: apiMock,
  unwrap: <T,>(envelope: { data?: T; error?: unknown }): T => {
    if (envelope.data !== undefined) return envelope.data;
    throw new Error('mock api error');
  },
}));

const ok = <T,>(data: T): { data: T } => ({ data });

describe('offline mutation replay integration', () => {
  beforeEach(() => {
    dbMock.rows.length = 0;
    apiMock.GET.mockReset();
    apiMock.POST.mockReset();
    apiMock.PATCH.mockReset();
    apiMock.DELETE.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('enqueues bucket updates and drains them FIFO on reconnect', async () => {
    apiMock.PATCH.mockResolvedValue(ok({ ok: true }));

    await enqueueMutation({
      type: 'email_bucket_update',
      emailId: 'email-1',
      bucket: 'must_read',
    });
    await enqueueMutation({
      type: 'email_bucket_update',
      emailId: 'email-2',
      bucket: 'ignore',
    });

    expect(await listPendingMutations()).toHaveLength(2);

    const queryClient = new QueryClient();
    const result = await replayPendingMutations(queryClient);

    expect(result).toEqual({ replayed: 2, failed: 0 });
    expect(await listPendingMutations()).toHaveLength(0);
    expect(apiMock.PATCH).toHaveBeenNthCalledWith(1, '/api/v1/emails/{email_id}/bucket', {
      params: { path: { email_id: 'email-1' } },
      body: { bucket: 'must_read' },
    });
    expect(apiMock.PATCH).toHaveBeenNthCalledWith(2, '/api/v1/emails/{email_id}/bucket', {
      params: { path: { email_id: 'email-2' } },
      body: { bucket: 'ignore' },
    });
  });

  it('records a replay failure on the queue row and stops draining', async () => {
    apiMock.PATCH.mockRejectedValueOnce(new Error('500 Internal Server Error'));

    const enqueued = await enqueueMutation({
      type: 'email_bucket_update',
      emailId: 'email-3',
      bucket: 'must_read',
    });
    await enqueueMutation({
      type: 'preferences_patch',
      body: { theme: 'dark' },
    });

    const queryClient = new QueryClient();
    const result = await replayPendingMutations(queryClient);

    expect(result).toEqual({ replayed: 0, failed: 1 });
    const queue = (await listPendingMutations()) as PendingMutationRecord[];
    expect(queue).toHaveLength(2);
    const failedRow = queue.find((row) => row.id === enqueued.id);
    expect(failedRow?.attempts).toBe(1);
    expect(failedRow?.lastError).toContain('500');
    expect(apiMock.PATCH).toHaveBeenCalledTimes(1);
  });

  it('removePendingMutation cancels a queued action without replaying it', async () => {
    const row = await enqueueMutation({
      type: 'unsubscribe_dismiss',
      suggestionId: 'suggest-1',
    });

    await removePendingMutation(row.id);

    expect(await listPendingMutations()).toHaveLength(0);
    expect(apiMock.POST).not.toHaveBeenCalled();
  });
});
