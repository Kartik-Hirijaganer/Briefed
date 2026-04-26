import { useQueryClient, type QueryKey } from '@tanstack/react-query';

import type { FreshnessState } from '@briefed/ui';

import { useOnlineStatus } from './useOnlineStatus';

/**
 * Options for {@link useFreshnessState}.
 */
export interface UseFreshnessStateOptions {
  /** TanStack Query key whose metadata drives the state. */
  readonly queryKey: QueryKey;
  /** Max age (ms) before a successful fetch is considered stale. */
  readonly staleTime: number;
}

/**
 * Computes one of the four plan §19.8 freshness states for a live query.
 * Components feed the result into `<FreshnessBadge>` so every data-bearing
 * view has a consistent label.
 *
 * @param options - Freshness inputs.
 * @returns State enum + the underlying last-known-good timestamp (ISO).
 */
export function useFreshnessState(options: UseFreshnessStateOptions): {
  state: FreshnessState;
  lastKnownGoodAt: string | null;
} {
  const online = useOnlineStatus();
  const client = useQueryClient();
  const state = client.getQueryState(options.queryKey);
  const lastKnownGoodAt =
    state?.dataUpdatedAt && state.dataUpdatedAt > 0
      ? new Date(state.dataUpdatedAt).toISOString()
      : null;

  if (!online) return { state: 'offline', lastKnownGoodAt };

  const failureCount = state?.fetchFailureCount ?? 0;
  if (failureCount > 0 && !state?.isInvalidated) {
    return { state: 'sync_failed', lastKnownGoodAt };
  }

  const ageMs = state?.dataUpdatedAt ? Date.now() - state.dataUpdatedAt : Infinity;
  if (ageMs > options.staleTime) return { state: 'stale', lastKnownGoodAt };
  return { state: 'fresh', lastKnownGoodAt };
}
