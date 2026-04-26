import Dexie, { type Table } from 'dexie';

/**
 * Generic key/value row stored in IndexedDB. Used by the TanStack Query
 * async-storage persister so cached digest data survives cold PWA opens.
 */
export interface OfflineKeyValueRecord {
  /** Storage key. */
  readonly key: string;
  /** Serialized value. */
  readonly value: string;
  /** Last write time in epoch ms. */
  readonly updatedAt: number;
}

/**
 * Kinds of state-changing operations that can be queued while offline.
 */
export type PendingMutationType =
  | 'account_patch'
  | 'email_bucket_update'
  | 'preferences_patch'
  | 'unsubscribe_confirm'
  | 'unsubscribe_dismiss';

/**
 * Serialized mutation payload kept in IndexedDB until replay succeeds.
 */
export type PendingMutationPayload =
  | {
      readonly type: 'account_patch';
      readonly accountId: string;
      readonly body: unknown;
    }
  | {
      readonly type: 'email_bucket_update';
      readonly emailId: string;
      readonly bucket: 'must_read' | 'good_to_read' | 'ignore' | 'waste';
    }
  | {
      readonly type: 'preferences_patch';
      readonly body: unknown;
    }
  | {
      readonly type: 'unsubscribe_confirm';
      readonly suggestionId: string;
    }
  | {
      readonly type: 'unsubscribe_dismiss';
      readonly suggestionId: string;
    };

/**
 * Durable pending mutation queue row.
 */
export interface PendingMutationRecord {
  /** Client-generated idempotency key. */
  readonly id: string;
  /** Indexed operation kind. */
  readonly type: PendingMutationType;
  /** Payload needed to replay the operation. */
  readonly payload: PendingMutationPayload;
  /** Creation time in epoch ms. */
  readonly createdAt: number;
  /** Replay attempts already made. */
  readonly attempts: number;
  /** Last replay error, if any. */
  readonly lastError?: string;
}

/**
 * Briefed's offline IndexedDB schema. Query cache and pending mutations
 * share one Dexie database so storage reporting and cleanup stay simple.
 */
export class BriefedOfflineDb extends Dexie {
  /** TanStack Query async-storage backing store. */
  public keyValues!: Table<OfflineKeyValueRecord, string>;
  /** FIFO queue of mutations captured while offline. */
  public pendingMutations!: Table<PendingMutationRecord, string>;

  /** Build the database and define the Phase 7 indexes. */
  public constructor() {
    super('briefed-offline');
    this.version(1).stores({
      keyValues: '&key, updatedAt',
      pendingMutations: '&id, type, createdAt, attempts',
    });
  }
}

/** Shared IndexedDB handle. */
export const offlineDb = new BriefedOfflineDb();
