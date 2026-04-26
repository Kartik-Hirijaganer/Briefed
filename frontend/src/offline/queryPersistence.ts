import { createAsyncStoragePersister } from '@tanstack/query-async-storage-persister';
import type { AsyncStorage } from '@tanstack/react-query-persist-client';

import { offlineDb } from './db';

const QUERY_CACHE_KEY = 'briefed-query-cache-v1';

const dexieAsyncStorage: AsyncStorage<string> = {
  async getItem(key: string): Promise<string | null> {
    const row = await offlineDb.keyValues.get(key);
    return row?.value ?? null;
  },
  async setItem(key: string, value: string): Promise<void> {
    await offlineDb.keyValues.put({ key, value, updatedAt: Date.now() });
  },
  async removeItem(key: string): Promise<void> {
    await offlineDb.keyValues.delete(key);
  },
};

/**
 * Async IndexedDB persister for TanStack Query.
 *
 * The max-age lives in `main.tsx` so the provider owns restore policy; this
 * module owns only storage mechanics and the stable cache key.
 */
export const queryPersister = createAsyncStoragePersister({
  storage: typeof indexedDB === 'undefined' ? undefined : dexieAsyncStorage,
  key: QUERY_CACHE_KEY,
  throttleTime: 1000,
});
