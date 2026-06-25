import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
} from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { useLocation, useSearchParams } from 'react-router-dom';

import type { FreshnessState } from '@briefed/ui';

import { api, unwrap } from '../../api/client';
import { digestToday, emails as emailsQueryKeyFactory } from '../../api/queryKeys';
import type { Schemas } from '../../api/types';
import type { Bucket } from '../../config/presentation';
import { useDemoMode } from '../../demo/DemoModeProvider';
import { useFreshnessState } from '../../hooks/useFreshnessState';
import { useOnlineStatus } from '../../hooks/useOnlineStatus';
import { usePullToRefresh } from '../../hooks/usePullToRefresh';
import { SCAN_NOW_EVENT } from './ScanNowButton';

const DIGEST_STALE_MS = 60 * 1000;
const EMAIL_STALE_MS = 2 * 60 * 1000;
const EMAIL_LIMIT = 25;
const EMPTY_EMAILS: readonly Schemas['EmailRow'][] = [];
const STALE_RUN_HOURS = 24 * 7;

/** Variables accepted by the mark-read mutation (kept as a list for the optimistic path). */
export interface MarkReadVariables {
  /** Email ids to mark read — called with a single id in the reader. */
  readonly emailIds: readonly string[];
}

interface OptimisticMarkReadContext {
  readonly previousEmails: Schemas['EmailsListResponse'] | undefined;
}

/** The mark-read mutation result, surfaced so `<MarkReadStatus>` can render feedback. */
export type MarkReadMutation = UseMutationResult<
  Schemas['MarkReadResponse'],
  Error,
  MarkReadVariables,
  OptimisticMarkReadContext
>;

/**
 * Everything the dashboard route shell and its child panes need. Centralizes
 * the digest + email queries, the optimistic mark-read mutation, the
 * `?bucket=&offset=&selected=` URL state, and the single-select reader model.
 */
export interface DashboardData {
  /** Live online status. */
  readonly online: boolean;
  /** Pull-to-refresh handlers spread onto the page root. */
  readonly pullToRefresh: ReturnType<typeof usePullToRefresh>;
  /** Today's digest payload (undefined while pending). */
  readonly digest: Schemas['DigestToday'] | undefined;
  /** Digest query is still loading. */
  readonly digestIsPending: boolean;
  /** Digest query failed. */
  readonly digestIsError: boolean;
  /** Digest query error, if any. */
  readonly digestError: unknown;
  /** Freshness state for the digest query. */
  readonly freshnessState: FreshnessState;
  /** Last-known-good timestamp for the freshness badge. */
  readonly freshnessLastKnownGoodAt: string | null;
  /** Last successful run timestamp from the digest. */
  readonly lastRunAt: string | null;
  /** Whether the last successful run is older than the stale threshold. */
  readonly autoScanMayBeOff: boolean;
  /** Active bucket filter, or null for "All". */
  readonly activeBucket: Bucket | null;
  /** Switch the active bucket filter (clears offset + selection). */
  readonly setBucket: (bucket: Bucket | null) => void;
  /** Loaded email rows for the current view. */
  readonly emails: readonly Schemas['EmailRow'][];
  /** Total rows in the current view. */
  readonly totalEmails: number;
  /** Emails query is loading. */
  readonly emailsIsPending: boolean;
  /** Emails query failed. */
  readonly emailsIsError: boolean;
  /** Emails query error, if any. */
  readonly emailsError: unknown;
  /** Current pagination offset. */
  readonly offset: number;
  /** Page size used for pagination math. */
  readonly pageSize: number;
  /** Whether a next page exists. */
  readonly hasNextPage: boolean;
  /** Jump to a pagination offset (clears selection). */
  readonly setOffset: (offset: number) => void;
  /** The resolved selected email (defaults to the first row). */
  readonly selectedEmail: Schemas['EmailRow'] | undefined;
  /** The resolved selected id, or null when the list is empty. */
  readonly selectedId: string | null;
  /**
   * Whether the user explicitly selected a row (an in-page `?selected=`), as
   * opposed to the default-first-row fallback. Drives the mobile list↔detail
   * swap.
   */
  readonly hasExplicitSelection: boolean;
  /** Select an email by id (URL `?selected=`). */
  readonly setSelectedId: (emailId: string | null) => void;
  /** Whether a later must-read row exists after the selection. */
  readonly hasNextMustRead: boolean;
  /** Advance the selection to the next must-read row. */
  readonly selectNextMustRead: () => void;
  /** Mark one email read and advance the selection to the next candidate. */
  readonly markOneRead: (emailId: string) => void;
  /** The mark-read mutation (for status feedback). */
  readonly markRead: MarkReadMutation;
  /** Ids currently checked for bulk mark-read (visible page only). */
  readonly selectedIds: ReadonlySet<string>;
  /** Count of checked rows among the visible page. */
  readonly selectedCount: number;
  /** Whether every visible row is checked. */
  readonly allSelected: boolean;
  /** Whether at least one visible row is checked. */
  readonly someSelected: boolean;
  /** Toggle one row's bulk-selection checkbox. */
  readonly toggleSelected: (emailId: string, checked: boolean) => void;
  /** Check or clear every visible row. */
  readonly toggleAllSelected: (checked: boolean) => void;
  /** Clear the bulk selection. */
  readonly clearSelection: () => void;
  /** Mark every checked row read (advances the reader off any marked row). */
  readonly markSelectedRead: () => void;
  /** Path to return to after a Gmail reconnect. */
  readonly reconnectReturnTo: string;
}

/**
 * Dashboard data + actions hook. Owns all queries, the optimistic mark-read
 * mutation, the URL-backed filter/pagination/selection state, and the
 * single-select reader navigation helpers.
 *
 * @returns The {@link DashboardData} bundle consumed by the route shell.
 */
export function useDashboardData(): DashboardData {
  const { isDemo } = useDemoMode();
  const online = useOnlineStatus();
  const queryClient = useQueryClient();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const activeBucket = parseBucket(searchParams.get('bucket'));
  const offset = parseOffset(searchParams.get('offset'));
  const selectedParam = searchParams.get('selected');
  const emailQueryParams =
    activeBucket === null
      ? { offset, limit: EMAIL_LIMIT }
      : { bucket: activeBucket, offset, limit: EMAIL_LIMIT };
  const emailsQueryKey = emailsQueryKeyFactory(emailQueryParams);

  const digestQuery = useQuery({
    queryKey: digestToday(),
    queryFn: async () => unwrap(await api.GET('/api/v1/digest/today')),
    staleTime: DIGEST_STALE_MS,
  });
  const emailsQuery = useQuery({
    queryKey: emailsQueryKey,
    queryFn: async () =>
      unwrap(
        await api.GET('/api/v1/emails', {
          params: { query: emailQueryParams },
        }),
      ),
    staleTime: EMAIL_STALE_MS,
  });
  const freshness = useFreshnessState({
    queryKey: digestToday(),
    staleTime: DIGEST_STALE_MS,
  });

  const markRead = useMutation<
    Schemas['MarkReadResponse'],
    Error,
    MarkReadVariables,
    OptimisticMarkReadContext
  >({
    mutationFn: async (variables) =>
      unwrap(
        await api.POST('/api/v1/emails/mark-read', {
          body: { email_ids: [...variables.emailIds] },
        }),
      ),
    onMutate: async (variables) => {
      await queryClient.cancelQueries({ queryKey: emailsQueryKeyFactory() });
      const previousEmails =
        queryClient.getQueryData<Schemas['EmailsListResponse']>(emailsQueryKey);
      const ids = new Set(variables.emailIds);
      queryClient.setQueryData<Schemas['EmailsListResponse']>(emailsQueryKey, (current) => {
        if (!current) return current;
        const nextEmails = current.emails.filter((email) => !ids.has(email.id));
        const removed = current.emails.length - nextEmails.length;
        return {
          emails: nextEmails,
          total: Math.max(0, current.total - removed),
        };
      });
      return { previousEmails };
    },
    onError: (_error, _variables, context) => {
      if (context?.previousEmails) {
        queryClient.setQueryData(emailsQueryKey, context.previousEmails);
      }
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: digestToday() });
      void queryClient.invalidateQueries({ queryKey: emailsQueryKeyFactory() });
    },
  });

  const [selectedIds, setSelectedIds] = useState<ReadonlySet<string>>(new Set<string>());

  const lastRunAt = digestQuery.data?.last_successful_run_at ?? null;
  const hoursSinceLastRun = lastRunAt
    ? (Date.now() - new Date(lastRunAt).getTime()) / (60 * 60 * 1000)
    : Infinity;
  const pullToRefresh = usePullToRefresh({
    disabled: isDemo || !online,
    onRefresh: () => window.dispatchEvent(new Event(SCAN_NOW_EVENT)),
  });
  const emails = emailsQuery.data?.emails ?? EMPTY_EMAILS;
  const totalEmails = emailsQuery.data?.total ?? 0;
  const hasNextPage = offset + EMAIL_LIMIT < totalEmails;
  const reconnectReturnTo = `${location.pathname}${location.search}${location.hash}` || '/app';

  const visibleIds = useMemo(() => emails.map((email) => email.id), [emails]);
  const selectedVisibleIds = visibleIds.filter((id) => selectedIds.has(id));
  const selectedCount = selectedVisibleIds.length;
  const allSelected = visibleIds.length > 0 && selectedCount === visibleIds.length;
  const someSelected = selectedCount > 0;

  // Drop ids that left the visible page (e.g. after a Scan Now refetch) so the
  // selection never carries rows the user can no longer see.
  useEffect(() => {
    setSelectedIds((current) => {
      if (current.size === 0) return current;
      const visible = new Set(visibleIds);
      const pruned = new Set([...current].filter((id) => visible.has(id)));
      return pruned.size === current.size ? current : pruned;
    });
  }, [visibleIds]);

  const selectedEmail = emails.find((email) => email.id === selectedParam) ?? emails[0];
  const selectedId = selectedEmail?.id ?? null;
  const hasExplicitSelection = selectedParam !== null && selectedEmail?.id === selectedParam;

  const nextMustRead = ((): Schemas['EmailRow'] | undefined => {
    const startIndex = selectedId ? emails.findIndex((email) => email.id === selectedId) : -1;
    return emails.slice(startIndex + 1).find((email) => email.bucket === 'must_read');
  })();
  const hasNextMustRead = nextMustRead !== undefined;

  const setSearchParam = (key: string, value: string | null, deleteSelected: boolean): void => {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    if (deleteSelected) next.delete('selected');
    setSearchParams(next, { replace: key === 'selected' });
  };

  const setBucket = (bucket: Bucket | null): void => {
    const next = new URLSearchParams(searchParams);
    if (bucket) next.set('bucket', bucket);
    else next.delete('bucket');
    next.delete('offset');
    next.delete('selected');
    setSearchParams(next, { replace: false });
    setSelectedIds(new Set<string>());
  };

  const setOffset = (nextOffset: number): void => {
    const next = new URLSearchParams(searchParams);
    if (nextOffset > 0) next.set('offset', String(nextOffset));
    else next.delete('offset');
    next.delete('selected');
    setSearchParams(next, { replace: false });
    setSelectedIds(new Set<string>());
  };

  const setSelectedId = (emailId: string | null): void => {
    setSearchParam('selected', emailId, false);
  };

  const selectNextMustRead = (): void => {
    if (nextMustRead) setSelectedId(nextMustRead.id);
  };

  const markOneRead = (emailId: string): void => {
    if (isDemo) return;
    // Capture the next selection BEFORE the optimistic removal mutates the
    // list — the row after the marked one (or the previous when it was last).
    const index = emails.findIndex((email) => email.id === emailId);
    const nextCandidate = emails[index + 1] ?? emails[index - 1] ?? undefined;
    markRead.mutate({ emailIds: [emailId] });
    setSelectedId(nextCandidate ? nextCandidate.id : null);
  };

  const toggleSelected = (emailId: string, checked: boolean): void => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (checked) next.add(emailId);
      else next.delete(emailId);
      return next;
    });
  };

  const toggleAllSelected = (checked: boolean): void => {
    setSelectedIds(checked ? new Set(visibleIds) : new Set<string>());
  };

  const clearSelection = (): void => setSelectedIds(new Set<string>());

  const markSelectedRead = (): void => {
    if (isDemo) return;
    const ids = selectedVisibleIds;
    if (ids.length === 0) return;
    const marked = new Set(ids);
    const previousSelection = selectedIds;

    // If the row open in the reading pane is being marked, advance the reader
    // selection BEFORE the optimistic removal mutates the list (mirrors
    // markOneRead): the next surviving row, else the previous, else clear.
    if (selectedId && marked.has(selectedId)) {
      const index = emails.findIndex((email) => email.id === selectedId);
      const nextCandidate =
        emails.slice(index + 1).find((email) => !marked.has(email.id)) ??
        [...emails.slice(0, index)].reverse().find((email) => !marked.has(email.id)) ??
        undefined;
      setSelectedId(nextCandidate ? nextCandidate.id : null);
    }

    clearSelection();
    markRead.mutate(
      { emailIds: ids },
      // The mutation-level onError rolls the cache back; restore the selection
      // here too so the user can retry without re-checking every row.
      { onError: () => setSelectedIds(previousSelection) },
    );
  };

  return {
    online,
    pullToRefresh,
    digest: digestQuery.data,
    digestIsPending: digestQuery.isPending,
    digestIsError: digestQuery.isError,
    digestError: digestQuery.error,
    freshnessState: freshness.state,
    freshnessLastKnownGoodAt: freshness.lastKnownGoodAt,
    lastRunAt,
    autoScanMayBeOff: digestQuery.data !== undefined && hoursSinceLastRun > STALE_RUN_HOURS,
    activeBucket,
    setBucket,
    emails,
    totalEmails,
    emailsIsPending: emailsQuery.isPending,
    emailsIsError: emailsQuery.isError,
    emailsError: emailsQuery.error,
    offset,
    pageSize: EMAIL_LIMIT,
    hasNextPage,
    setOffset,
    selectedEmail,
    selectedId,
    hasExplicitSelection,
    setSelectedId,
    hasNextMustRead,
    selectNextMustRead,
    markOneRead,
    markRead,
    selectedIds,
    selectedCount,
    allSelected,
    someSelected,
    toggleSelected,
    toggleAllSelected,
    clearSelection,
    markSelectedRead,
    reconnectReturnTo,
  };
}

/**
 * Parse a URL search parameter into a supported bucket filter.
 *
 * @param value - Raw `bucket` query string value.
 * @returns The parsed bucket, or `null` when unset/unsupported.
 */
function parseBucket(value: string | null): Bucket | null {
  if (value === 'must_read' || value === 'good_to_read' || value === 'ignore') return value;
  return null;
}

/**
 * Parse and clamp a URL offset value.
 *
 * @param value - Raw `offset` query string value.
 * @returns A non-negative integer offset.
 */
function parseOffset(value: string | null): number {
  const parsed = Number.parseInt(value ?? '0', 10);
  if (!Number.isFinite(parsed) || parsed < 0) return 0;
  return parsed;
}
