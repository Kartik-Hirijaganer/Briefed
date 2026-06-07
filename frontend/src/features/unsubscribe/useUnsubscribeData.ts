import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';

import type { FreshnessState } from '@briefed/ui';

import { api, unwrap } from '../../api/client';
import type { Schemas } from '../../api/types';
import { useFreshnessState } from '../../hooks/useFreshnessState';
import { useOnlineStatus } from '../../hooks/useOnlineStatus';
import { enqueueMutation } from '../../offline/mutations';
import { flaggedCount, preferredUnsubscribeUrl, wastedEmailsPerMonth } from './unsubscribeDerived';

type Suggestion = Schemas['UnsubscribeSuggestion'];

const STALE_MS = 10 * 60 * 1000;
const EMPTY_SUGGESTIONS: readonly Suggestion[] = [];

/**
 * Per-row execute outcome retained on the card (ADR 0014). ``unsubscribed``
 * rows are removed from the list rather than stored, so only the
 * still-actionable states live here.
 */
export interface ExecuteResultEntry {
  /** Outcome that keeps the card on screen. */
  readonly status: 'manual_required' | 'failed';
  /** URL the user must open for ``manual_required``; ``null`` otherwise. */
  readonly manualUrl: string | null;
  /** Human-readable message for the card affordance. */
  readonly message: string;
}

/** Aggregate counts from the most recent execute batch (for the results panel). */
export interface ExecuteBatchSummary {
  /** Senders unsubscribed via one-click. */
  readonly unsubscribed: number;
  /** Senders needing a manual step. */
  readonly manualRequired: number;
  /** Senders that failed. */
  readonly failed: number;
}

/**
 * Remove one suggestion from the cached list (shared optimistic helper so the
 * card actions and the bulk actions never drift).
 *
 * @param client - The active query client.
 * @param suggestionId - Row to drop from the cache.
 */
export function removeSuggestionFromCache(client: QueryClient, suggestionId: string): void {
  client.setQueryData<Schemas['UnsubscribesListResponse']>(['unsubscribes'], (current) => {
    if (!current) return current;
    return {
      suggestions: current.suggestions.filter((suggestion) => suggestion.id !== suggestionId),
    };
  });
}

/**
 * Data + actions for the unsubscribe page. Owns the suggestions query, the
 * runtime execute capability, the multi-select state, and the recommend-only
 * bulk actions (Keep + recommend-only Unsubscribe). The destructive execute
 * path layers on top in Track 5 behind {@link UnsubscribeData.executeEnabled}.
 */
export interface UnsubscribeData {
  /** Currently displayed suggestions. */
  readonly suggestions: readonly Suggestion[];
  /** Suggestions query is loading. */
  readonly isPending: boolean;
  /** Suggestions query failed. */
  readonly isError: boolean;
  /** Suggestions query error. */
  readonly error: unknown;
  /** Freshness state for the suggestions query. */
  readonly freshnessState: FreshnessState;
  /** Last-known-good timestamp for the freshness badge. */
  readonly freshnessLastKnownGoodAt: string | null;
  /** Live online status. */
  readonly online: boolean;
  /** Whether the execute-unsubscribe capability is enabled (ADR 0014). */
  readonly executeEnabled: boolean;
  /** Set of selected suggestion ids. */
  readonly selectedIds: ReadonlySet<string>;
  /** Number of selected rows. */
  readonly selectedCount: number;
  /** Total number of displayed rows. */
  readonly totalCount: number;
  /** Whether every displayed row is selected. */
  readonly allSelected: boolean;
  /** Whether some (but not necessarily all) rows are selected. */
  readonly someSelected: boolean;
  /** Number of flagged senders (header count). */
  readonly flaggedCount: number;
  /** Estimated wasted emails per month across flagged senders. */
  readonly wastedPerMonth: number;
  /** Toggle one row's selection. */
  readonly toggleSelected: (suggestionId: string, checked: boolean) => void;
  /** Select or clear every displayed row. */
  readonly togglePageSelected: (checked: boolean) => void;
  /** Clear the selection. */
  readonly clearSelection: () => void;
  /** Keep (dismiss) every selected sender. */
  readonly keepSelected: () => void;
  /** Whether a Keep batch is in flight. */
  readonly keepBusy: boolean;
  /**
   * Recommend-only bulk unsubscribe (capability OFF): synchronously open each
   * selected sender's preferred URL in a new tab and mark each handled.
   */
  readonly recommendUnsubscribeSelected: () => void;
  /** Whether the primary bulk action is in flight. */
  readonly primaryBusy: boolean;
  /** Per-row execute outcomes that keep a card on screen (manual/failed). */
  readonly executeResults: ReadonlyMap<string, ExecuteResultEntry>;
  /** Counts from the most recent execute batch, or null when none has run. */
  readonly batchSummary: ExecuteBatchSummary | null;
  /**
   * Destructive bulk execute (capability ON): POST ``/execute`` per selected
   * sender, then apply per-result transitions (remove / keep+manual / keep+error).
   */
  readonly executeSelected: () => Promise<void>;
  /** Mark a ``manual_required`` row handled (the user finished it themselves). */
  readonly confirmManual: (suggestionId: string) => void;
  /** Retry a single failed execute. */
  readonly retryExecute: (suggestionId: string) => Promise<void>;
  /** Clear the batch results panel. */
  readonly dismissBatchSummary: () => void;
}

/**
 * Unsubscribe page data + actions hook.
 *
 * @returns The {@link UnsubscribeData} bundle consumed by the page shell.
 */
export function useUnsubscribeData(): UnsubscribeData {
  const client = useQueryClient();
  const online = useOnlineStatus();
  const [selectedIds, setSelectedIds] = useState<ReadonlySet<string>>(new Set<string>());
  const [executeResults, setExecuteResults] = useState<ReadonlyMap<string, ExecuteResultEntry>>(
    new Map<string, ExecuteResultEntry>(),
  );
  const [batchSummary, setBatchSummary] = useState<ExecuteBatchSummary | null>(null);

  const suggestionsQuery = useQuery({
    queryKey: ['unsubscribes'],
    queryFn: async () => unwrap(await api.GET('/api/v1/unsubscribes')),
    staleTime: STALE_MS,
  });
  const configQuery = useQuery({
    queryKey: ['client-config'],
    queryFn: async () => unwrap(await api.GET('/api/v1/config')),
    staleTime: Infinity,
  });
  const freshness = useFreshnessState({ queryKey: ['unsubscribes'], staleTime: STALE_MS });

  const dismiss = useMutation({
    mutationFn: async (id: string): Promise<void> => {
      if (!online) {
        await enqueueMutation({ type: 'unsubscribe_dismiss', suggestionId: id });
        return;
      }
      unwrap(
        await api.POST('/api/v1/unsubscribes/{suggestion_id}/dismiss', {
          params: { path: { suggestion_id: id } },
        }),
      );
    },
    onMutate: (id) => removeSuggestionFromCache(client, id),
    onSuccess: () => invalidateUnsubscribe(client, online),
  });

  const confirm = useMutation({
    mutationFn: async (id: string): Promise<void> => {
      if (!online) {
        await enqueueMutation({ type: 'unsubscribe_confirm', suggestionId: id });
        return;
      }
      unwrap(
        await api.POST('/api/v1/unsubscribes/{suggestion_id}/confirm', {
          params: { path: { suggestion_id: id } },
        }),
      );
    },
    onMutate: (id) => removeSuggestionFromCache(client, id),
    onSuccess: () => invalidateUnsubscribe(client, online),
  });

  const execute = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.POST('/api/v1/unsubscribes/{suggestion_id}/execute', {
          params: { path: { suggestion_id: id } },
          body: { confirm: true },
        }),
      ),
  });

  const suggestions = suggestionsQuery.data?.suggestions ?? EMPTY_SUGGESTIONS;
  const visibleIds = useMemo(() => suggestions.map((s) => s.id), [suggestions]);
  const selectedCount = visibleIds.filter((id) => selectedIds.has(id)).length;
  const totalCount = visibleIds.length;
  const allSelected = totalCount > 0 && selectedCount === totalCount;
  const someSelected = selectedCount > 0;

  const toggleSelected = (suggestionId: string, checked: boolean): void => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (checked) next.add(suggestionId);
      else next.delete(suggestionId);
      return next;
    });
  };
  const togglePageSelected = (checked: boolean): void => {
    setSelectedIds(checked ? new Set(visibleIds) : new Set<string>());
  };
  const clearSelection = (): void => setSelectedIds(new Set<string>());

  const selectedSuggestions = (): readonly Suggestion[] =>
    suggestions.filter((s) => selectedIds.has(s.id));

  const keepSelected = (): void => {
    const ids = selectedSuggestions().map((s) => s.id);
    if (ids.length === 0) return;
    clearSelection();
    void Promise.allSettled(ids.map((id) => dismiss.mutateAsync(id)));
  };

  const recommendUnsubscribeSelected = (): void => {
    const selected = selectedSuggestions();
    if (selected.length === 0) return;
    // Open tabs synchronously with the user gesture so the popup blocker does
    // not eat them, then mark each handled via the existing /confirm path.
    for (const suggestion of selected) {
      const url = preferredUnsubscribeUrl(suggestion);
      if (url) window.open(url, '_blank', 'noopener,noreferrer');
      confirm.mutate(suggestion.id);
    }
    clearSelection();
  };

  const executeSelected = async (): Promise<void> => {
    const ids = selectedSuggestions().map((s) => s.id);
    if (ids.length === 0) return;
    const outcomes = await Promise.all(
      ids.map(async (id) => {
        try {
          return { id, result: await execute.mutateAsync(id) } as const;
        } catch {
          return { id, result: null } as const;
        }
      }),
    );
    const next = new Map(executeResults);
    let unsubscribed = 0;
    let manualRequired = 0;
    let failed = 0;
    for (const { id, result } of outcomes) {
      const status = applyExecuteOutcome(client, next, id, result);
      if (status === 'unsubscribed') unsubscribed += 1;
      else if (status === 'manual_required') manualRequired += 1;
      else failed += 1;
    }
    setExecuteResults(next);
    setBatchSummary({ unsubscribed, manualRequired, failed });
    clearSelection();
    invalidateUnsubscribe(client, online);
  };

  const confirmManual = (id: string): void => {
    confirm.mutate(id);
    setExecuteResults((current) => {
      const next = new Map(current);
      next.delete(id);
      return next;
    });
  };

  const retryExecute = async (id: string): Promise<void> => {
    let result: Awaited<ReturnType<typeof execute.mutateAsync>> | null = null;
    try {
      result = await execute.mutateAsync(id);
    } catch {
      result = null;
    }
    setExecuteResults((current) => {
      const next = new Map(current);
      applyExecuteOutcome(client, next, id, result);
      return next;
    });
    invalidateUnsubscribe(client, online);
  };

  const dismissBatchSummary = (): void => setBatchSummary(null);

  return {
    suggestions,
    isPending: suggestionsQuery.isPending,
    isError: suggestionsQuery.isError,
    error: suggestionsQuery.error,
    freshnessState: freshness.state,
    freshnessLastKnownGoodAt: freshness.lastKnownGoodAt,
    online,
    executeEnabled: configQuery.data?.unsubscribe_execute ?? false,
    selectedIds,
    selectedCount,
    totalCount,
    allSelected,
    someSelected,
    flaggedCount: flaggedCount(suggestions),
    wastedPerMonth: wastedEmailsPerMonth(suggestions),
    toggleSelected,
    togglePageSelected,
    clearSelection,
    keepSelected,
    keepBusy: dismiss.isPending,
    recommendUnsubscribeSelected,
    primaryBusy: execute.isPending || confirm.isPending,
    executeResults,
    batchSummary,
    executeSelected,
    confirmManual,
    retryExecute,
    dismissBatchSummary,
  };
}

/**
 * Invalidate the unsubscribe + hygiene caches after a mutation (online only).
 *
 * @param client - The active query client.
 * @param online - Whether the app is online (offline mutations replay later).
 */
function invalidateUnsubscribe(client: QueryClient, online: boolean): void {
  if (!online) return;
  void client.invalidateQueries({ queryKey: ['unsubscribes'] });
  void client.invalidateQueries({ queryKey: ['hygiene'] });
}

/**
 * Apply one execute outcome: drop unsubscribed rows from both the cache and the
 * results map, or record a manual/failed entry to keep the card on screen.
 *
 * @param client - The active query client.
 * @param results - Mutable results map being assembled.
 * @param id - Suggestion id.
 * @param result - The execute response, or ``null`` when the request failed.
 * @returns The resolved status applied.
 */
function applyExecuteOutcome(
  client: QueryClient,
  results: Map<string, ExecuteResultEntry>,
  id: string,
  result: Schemas['UnsubscribeExecuteResponse'] | null,
): 'unsubscribed' | 'manual_required' | 'failed' {
  if (result === null) {
    results.set(id, {
      status: 'failed',
      manualUrl: null,
      message: 'The request could not be completed.',
    });
    return 'failed';
  }
  if (result.status === 'unsubscribed') {
    removeSuggestionFromCache(client, id);
    results.delete(id);
    return 'unsubscribed';
  }
  if (result.status === 'manual_required') {
    results.set(id, {
      status: 'manual_required',
      manualUrl: result.manual_url ?? null,
      message: result.message,
    });
    return 'manual_required';
  }
  results.set(id, { status: 'failed', manualUrl: null, message: result.message });
  return 'failed';
}
