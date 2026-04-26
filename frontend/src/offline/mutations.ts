import type { QueryClient } from '@tanstack/react-query';

import { api, unwrap } from '../api/client';
import type { Schemas } from '../api/types';

import {
  offlineDb,
  type PendingMutationPayload,
  type PendingMutationRecord,
  type PendingMutationType,
} from './db';

const CHANGE_EVENT = 'briefed-pending-mutations-changed';
const MAX_ATTEMPTS = 5;

/**
 * Unsubscribe to pending-mutation queue changes.
 *
 * @param listener - Callback invoked after queue writes.
 * @returns Cleanup callback.
 */
export function subscribeToPendingMutations(listener: () => void): () => void {
  window.addEventListener(CHANGE_EVENT, listener);
  return () => window.removeEventListener(CHANGE_EVENT, listener);
}

/**
 * Notify React hooks that the durable queue changed.
 */
export function notifyPendingMutationsChanged(): void {
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

/**
 * Return the current pending mutation list in replay order.
 *
 * @returns Pending records ordered FIFO.
 */
export async function listPendingMutations(): Promise<PendingMutationRecord[]> {
  return offlineDb.pendingMutations.orderBy('createdAt').toArray();
}

/**
 * Delete one queued operation, usually after user cancellation or replay.
 *
 * @param id - Pending mutation id.
 */
export async function removePendingMutation(id: string): Promise<void> {
  await offlineDb.pendingMutations.delete(id);
  notifyPendingMutationsChanged();
}

/**
 * Add a mutation to IndexedDB for later replay.
 *
 * @param payload - Serialized operation.
 * @returns The durable queue row.
 */
export async function enqueueMutation(
  payload: PendingMutationPayload,
): Promise<PendingMutationRecord> {
  const record: PendingMutationRecord = {
    id: createMutationId(),
    type: payload.type as PendingMutationType,
    payload,
    createdAt: Date.now(),
    attempts: 0,
  };
  await offlineDb.pendingMutations.add(record);
  notifyPendingMutationsChanged();
  return record;
}

/**
 * Replay pending mutations FIFO until the queue is empty or one replay fails.
 *
 * @param queryClient - Query client used for post-replay invalidation.
 * @returns Summary counts.
 */
export async function replayPendingMutations(queryClient: QueryClient): Promise<{
  replayed: number;
  failed: number;
}> {
  const pending = await listPendingMutations();
  let replayed = 0;
  let failed = 0;

  for (const record of pending) {
    if (record.attempts >= MAX_ATTEMPTS) {
      failed += 1;
      continue;
    }

    try {
      await executePendingMutation(record);
      await removePendingMutation(record.id);
      invalidateAfterReplay(queryClient, record);
      replayed += 1;
    } catch (error) {
      failed += 1;
      await offlineDb.pendingMutations.update(record.id, {
        attempts: record.attempts + 1,
        lastError: error instanceof Error ? error.message : 'Replay failed',
      });
      notifyPendingMutationsChanged();
      break;
    }
  }

  return { replayed, failed };
}

async function executePendingMutation(record: PendingMutationRecord): Promise<void> {
  switch (record.payload.type) {
    case 'account_patch':
      unwrap(
        await api.PATCH('/api/v1/accounts/{account_id}', {
          params: { path: { account_id: record.payload.accountId } },
          body: record.payload.body as Schemas['AccountPatchRequest'],
        }),
      );
      return;
    case 'email_bucket_update':
      unwrap(
        await api.PATCH('/api/v1/emails/{email_id}/bucket', {
          params: { path: { email_id: record.payload.emailId } },
          body: { bucket: record.payload.bucket },
        }),
      );
      return;
    case 'preferences_patch':
      unwrap(
        await api.PATCH('/api/v1/preferences', {
          body: record.payload.body as Schemas['PreferencesPatchRequest'],
        }),
      );
      return;
    case 'unsubscribe_confirm':
      unwrap(
        await api.POST('/api/v1/unsubscribes/{suggestion_id}/confirm', {
          params: { path: { suggestion_id: record.payload.suggestionId } },
        }),
      );
      return;
    case 'unsubscribe_dismiss':
      unwrap(
        await api.POST('/api/v1/unsubscribes/{suggestion_id}/dismiss', {
          params: { path: { suggestion_id: record.payload.suggestionId } },
        }),
      );
      return;
  }
}

function invalidateAfterReplay(queryClient: QueryClient, record: PendingMutationRecord): void {
  switch (record.payload.type) {
    case 'account_patch':
      void queryClient.invalidateQueries({ queryKey: ['accounts'] });
      return;
    case 'email_bucket_update':
      void queryClient.invalidateQueries({ queryKey: ['digest-today'] });
      void queryClient.invalidateQueries({ queryKey: ['emails'] });
      return;
    case 'preferences_patch':
      void queryClient.invalidateQueries({ queryKey: ['preferences'] });
      return;
    case 'unsubscribe_confirm':
    case 'unsubscribe_dismiss':
      void queryClient.invalidateQueries({ queryKey: ['unsubscribes'] });
      void queryClient.invalidateQueries({ queryKey: ['hygiene'] });
      return;
  }
}

function createMutationId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }
  return `mutation-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
