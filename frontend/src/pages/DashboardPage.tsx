import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { UseMutationResult } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  FreshnessBadge,
  OpenInGmailLink,
  SafeMarkdown,
  Skeleton,
  type BadgeTone,
} from '@briefed/ui';

import { api, unwrap } from '../api/client';
import type { Schemas } from '../api/types';
import { SCAN_NOW_EVENT, ScanNowButton } from '../features/dashboard/ScanNowButton';
import { useFreshnessState } from '../hooks/useFreshnessState';
import { useOnlineStatus } from '../hooks/useOnlineStatus';
import { usePullToRefresh } from '../hooks/usePullToRefresh';

const DIGEST_STALE_MS = 60 * 1000;
const EMAIL_STALE_MS = 2 * 60 * 1000;
const EMAIL_LIMIT = 25;
const EMPTY_EMAILS: readonly Schemas['EmailRow'][] = [];

type Bucket = Schemas['EmailRow']['bucket'];

interface BucketMeta {
  readonly label: string;
  readonly tone: BadgeTone;
}

const BUCKET_META: Record<Bucket, BucketMeta> = {
  must_read: { label: 'Must-Read', tone: 'accent' },
  good_to_read: { label: 'Good-to-Read', tone: 'success' },
  ignore: { label: 'Ignore', tone: 'neutral' },
};

const BUCKETS: readonly Bucket[] = ['must_read', 'good_to_read', 'ignore'];

interface MarkReadVariables {
  readonly emailIds: readonly string[];
}

interface OptimisticMarkReadContext {
  readonly previousEmails: Schemas['EmailsListResponse'] | undefined;
}

/**
 * Dashboard page (`/`). Renders the Phase 6 single daily brief: category
 * narrative cards, KPI filters, paginated tagged email table, and mark-read
 * actions backed by Gmail.
 *
 * @returns The rendered page.
 */
export default function DashboardPage(): JSX.Element {
  const online = useOnlineStatus();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const [selectedIds, setSelectedIds] = useState<ReadonlySet<string>>(new Set<string>());
  const activeBucket = parseBucket(searchParams.get('bucket'));
  const offset = parseOffset(searchParams.get('offset'));
  const emailQueryParams =
    activeBucket === null
      ? { offset, limit: EMAIL_LIMIT }
      : { bucket: activeBucket, offset, limit: EMAIL_LIMIT };
  const emailsQueryKey = ['emails', emailQueryParams] as const;

  const digestQuery = useQuery({
    queryKey: ['digest-today'],
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
    queryKey: ['digest-today'],
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
      await queryClient.cancelQueries({ queryKey: ['emails'] });
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
      setSelectedIds(new Set<string>());
      return { previousEmails };
    },
    onError: (_error, _variables, context) => {
      if (context?.previousEmails) {
        queryClient.setQueryData(emailsQueryKey, context.previousEmails);
      }
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ['digest-today'] });
      void queryClient.invalidateQueries({ queryKey: ['emails'] });
    },
  });

  const lastRunAt = digestQuery.data?.last_successful_run_at ?? null;
  const hoursSinceLastRun = lastRunAt
    ? (Date.now() - new Date(lastRunAt).getTime()) / (60 * 60 * 1000)
    : Infinity;
  const pullToRefresh = usePullToRefresh({
    disabled: !online,
    onRefresh: () => window.dispatchEvent(new Event(SCAN_NOW_EVENT)),
  });
  const digest = digestQuery.data;
  const emails = emailsQuery.data?.emails ?? EMPTY_EMAILS;
  const totalEmails = emailsQuery.data?.total ?? 0;
  const visibleIds = useMemo(() => emails.map((email) => email.id), [emails]);
  const selectedCount = visibleIds.filter((id) => selectedIds.has(id)).length;
  const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedIds.has(id));
  const hasNextPage = offset + EMAIL_LIMIT < totalEmails;

  useEffect(() => {
    setSelectedIds(new Set<string>());
  }, [activeBucket, offset]);

  const setBucket = (bucket: Bucket | null): void => {
    const nextParams = new URLSearchParams(searchParams);
    if (bucket) nextParams.set('bucket', bucket);
    else nextParams.delete('bucket');
    nextParams.delete('offset');
    setSearchParams(nextParams, { replace: false });
  };

  const setOffset = (nextOffset: number): void => {
    const nextParams = new URLSearchParams(searchParams);
    if (nextOffset > 0) nextParams.set('offset', String(nextOffset));
    else nextParams.delete('offset');
    setSearchParams(nextParams, { replace: false });
  };

  const toggleSelected = (emailId: string, checked: boolean): void => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (checked) next.add(emailId);
      else next.delete(emailId);
      return next;
    });
  };

  const togglePageSelected = (checked: boolean): void => {
    setSelectedIds(checked ? new Set(visibleIds) : new Set<string>());
  };

  const markSelectedRead = (): void => {
    const ids = visibleIds.filter((id) => selectedIds.has(id));
    if (ids.length === 0) return;
    markRead.mutate({ emailIds: ids });
  };

  return (
    <section className="flex flex-col gap-6" {...pullToRefresh}>
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-semibold tracking-tight">Today&apos;s Digest</h1>
          <div className="flex flex-wrap items-center gap-3">
            <FreshnessBadge
              state={freshness.state}
              lastKnownGoodAt={lastRunAt ?? freshness.lastKnownGoodAt ?? undefined}
            />
            {digest ? (
              <span className="text-xs text-fg-muted">
                {digest.rule_decided} sorted by your rules (free)
              </span>
            ) : null}
          </div>
        </div>
        <ScanNowButton />
      </header>

      {hoursSinceLastRun > 24 * 7 ? (
        <Alert tone="warn" title="Auto-scan may be off">
          <p>
            It has been more than 7 days since the last successful scan. Run a manual scan or
            re-enable auto-scans in settings.
          </p>
        </Alert>
      ) : null}

      {digestQuery.isPending ? (
        <DigestSkeleton />
      ) : digestQuery.isError ? (
        <ErrorState
          title="Could not load today's digest"
          detail={digestQuery.error instanceof Error ? digestQuery.error.message : undefined}
        />
      ) : digest ? (
        <>
          <DigestSummary digest={digest} activeBucket={activeBucket} onSelectBucket={setBucket} />
          <EmailTable
            activeBucket={activeBucket}
            allVisibleSelected={allVisibleSelected}
            emails={emails}
            error={emailsQuery.error}
            hasNextPage={hasNextPage}
            isError={emailsQuery.isError}
            isPending={emailsQuery.isPending}
            markReadPending={markRead.isPending}
            offset={offset}
            onMarkRead={(emailId) => markRead.mutate({ emailIds: [emailId] })}
            onNextPage={() => setOffset(offset + EMAIL_LIMIT)}
            onPreviousPage={() => setOffset(Math.max(0, offset - EMAIL_LIMIT))}
            onTogglePageSelected={togglePageSelected}
            onToggleSelected={toggleSelected}
            selectedCount={selectedCount}
            selectedIds={selectedIds}
            total={totalEmails}
            onMarkSelectedRead={markSelectedRead}
          />
          <MarkReadStatus mutation={markRead} />
        </>
      ) : null}
    </section>
  );
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

/**
 * Loading blocks for the digest header and table.
 *
 * @returns The rendered skeletons.
 */
function DigestSkeleton(): JSX.Element {
  return (
    <>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Skeleton shape="block" />
        <Skeleton shape="block" />
        <Skeleton shape="block" />
        <Skeleton shape="block" />
      </div>
      <Skeleton shape="block" />
    </>
  );
}

interface DigestSummaryProps {
  readonly digest: Schemas['DigestToday'];
  readonly activeBucket: Bucket | null;
  readonly onSelectBucket: (bucket: Bucket | null) => void;
}

/**
 * Render category narrative cards and KPI filter cards.
 *
 * @param props - Component props.
 * @returns The rendered digest summary region.
 */
function DigestSummary(props: DigestSummaryProps): JSX.Element {
  const { digest, activeBucket, onSelectBucket } = props;
  const summaries = digest.category_summaries;
  const allCount = digest.counts.must_read + digest.counts.good_to_read + digest.counts.ignore;

  return (
    <div className="flex flex-col gap-4">
      {summaries.length > 0 ? (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {summaries.map((summary) => (
            <CategorySummaryCard key={summary.category} summary={summary} />
          ))}
        </div>
      ) : null}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KpiButton
          active={activeBucket === null}
          label="All"
          value={allCount}
          onClick={() => onSelectBucket(null)}
        />
        {BUCKETS.map((bucket) => (
          <KpiButton
            key={bucket}
            active={activeBucket === bucket}
            label={BUCKET_META[bucket].label}
            value={digest.counts[bucket]}
            tone={bucket === 'must_read' ? 'accent' : 'neutral'}
            onClick={() => onSelectBucket(bucket)}
          />
        ))}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-fg-muted">
        <span>Today&apos;s cost: ${(digest.cost_cents_today / 100).toFixed(2)}</span>
        <Link to="/unsubscribe" className="text-accent underline-offset-4 hover:underline">
          Review unsubscribe suggestions
        </Link>
      </div>
    </div>
  );
}

interface CategorySummaryCardProps {
  readonly summary: Schemas['DigestToday']['category_summaries'][number];
}

/**
 * Render one per-category narrative summary with sanitized markdown.
 *
 * @param props - Component props.
 * @returns The rendered summary card.
 */
function CategorySummaryCard(props: CategorySummaryCardProps): JSX.Element {
  const { summary } = props;
  const meta = BUCKET_META[summary.category];
  const headingClass = summary.category === 'must_read' ? 'text-accent' : 'text-fg';

  return (
    <Card className="flex flex-col gap-3">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <h2 className={`text-lg font-semibold ${headingClass}`}>{meta.label}</h2>
        <Badge tone={summary.confidence < 0.75 ? 'warn' : meta.tone}>
          {Math.round(summary.confidence * 100)}% confidence
        </Badge>
      </header>
      <SafeMarkdown className="max-w-[var(--measure)] text-sm leading-6 text-fg-muted">
        {summary.narrative}
      </SafeMarkdown>
      {summary.groups.length > 0 ? (
        <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
          {summary.groups.map((group) => (
            <div key={group.label} className="rounded-[var(--radius-sm)] bg-bg-muted p-3">
              <h3 className="text-sm font-semibold text-fg">{group.label}</h3>
              <ul className="mt-1 list-disc pl-4 text-sm text-fg-muted">
                {group.bullets.map((bullet) => (
                  <li key={bullet}>{bullet}</li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      ) : null}
    </Card>
  );
}

interface KpiButtonProps {
  readonly active: boolean;
  readonly label: string;
  readonly value: number;
  readonly tone?: 'accent' | 'neutral';
  readonly onClick: () => void;
}

/**
 * Clickable KPI card that filters the email table.
 *
 * @param props - Component props.
 * @returns The rendered button.
 */
function KpiButton(props: KpiButtonProps): JSX.Element {
  const { active, label, value, tone = 'neutral', onClick } = props;
  const valueClass = tone === 'accent' ? 'text-accent' : 'text-fg';
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`rounded-[var(--radius-md)] border bg-surface p-4 text-left transition-colors ${
        active
          ? 'border-accent shadow-[var(--shadow-1)]'
          : 'border-border hover:border-border-strong'
      }`}
    >
      <span className="text-xs uppercase tracking-wide text-fg-muted">{label}</span>
      <span className={`mt-1 block text-2xl font-semibold ${valueClass}`}>{value}</span>
    </button>
  );
}

interface EmailTableProps {
  readonly activeBucket: Bucket | null;
  readonly allVisibleSelected: boolean;
  readonly emails: readonly Schemas['EmailRow'][];
  readonly error: unknown;
  readonly hasNextPage: boolean;
  readonly isError: boolean;
  readonly isPending: boolean;
  readonly markReadPending: boolean;
  readonly offset: number;
  readonly selectedCount: number;
  readonly selectedIds: ReadonlySet<string>;
  readonly total: number;
  readonly onMarkRead: (emailId: string) => void;
  readonly onMarkSelectedRead: () => void;
  readonly onNextPage: () => void;
  readonly onPreviousPage: () => void;
  readonly onTogglePageSelected: (checked: boolean) => void;
  readonly onToggleSelected: (emailId: string, checked: boolean) => void;
}

/**
 * Paginated email table with category tags, row actions, selection, and
 * mobile stacked cards.
 *
 * @param props - Component props.
 * @returns The rendered table region.
 */
function EmailTable(props: EmailTableProps): JSX.Element {
  const {
    activeBucket,
    allVisibleSelected,
    emails,
    error,
    hasNextPage,
    isError,
    isPending,
    markReadPending,
    offset,
    selectedCount,
    selectedIds,
    total,
    onMarkRead,
    onMarkSelectedRead,
    onNextPage,
    onPreviousPage,
    onTogglePageSelected,
    onToggleSelected,
  } = props;
  const title = activeBucket ? `${BUCKET_META[activeBucket].label} emails` : 'All emails';

  return (
    <section className="flex flex-col gap-3" aria-labelledby="email-table-heading">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 id="email-table-heading" className="text-xl font-semibold">
            {title}
          </h2>
          <p className="text-sm text-fg-muted">{total} unread messages in this view</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={onMarkSelectedRead}
            disabled={selectedCount === 0 || markReadPending}
            loading={markReadPending && selectedCount > 0}
          >
            Mark selected read
          </Button>
        </div>
      </header>

      {isPending ? (
        <div className="flex flex-col gap-3">
          <Skeleton shape="block" />
          <Skeleton shape="block" />
          <Skeleton shape="block" />
        </div>
      ) : isError ? (
        <ErrorState
          title="Could not load emails"
          detail={error instanceof Error ? error.message : undefined}
        />
      ) : emails.length > 0 ? (
        <>
          <div className="hidden overflow-x-auto rounded-[var(--radius-md)] border border-border bg-surface md:block">
            <table className="w-full border-collapse text-sm">
              <thead className="bg-bg-muted text-left text-xs uppercase tracking-wide text-fg-muted">
                <tr>
                  <th className="w-10 px-3 py-3">
                    <input
                      type="checkbox"
                      checked={allVisibleSelected}
                      onChange={(event) => onTogglePageSelected(event.target.checked)}
                      aria-label="Select all visible emails"
                    />
                  </th>
                  <th className="px-3 py-3">Category</th>
                  <th className="px-3 py-3">Sender</th>
                  <th className="px-3 py-3">Subject</th>
                  <th className="px-3 py-3">Received</th>
                  <th className="px-3 py-3">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {emails.map((email) => (
                  <EmailTableRow
                    key={email.id}
                    email={email}
                    markReadPending={markReadPending}
                    selected={selectedIds.has(email.id)}
                    onMarkRead={onMarkRead}
                    onToggleSelected={onToggleSelected}
                  />
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex flex-col gap-3 md:hidden">
            <label className="flex items-center gap-2 text-sm text-fg">
              <input
                type="checkbox"
                checked={allVisibleSelected}
                onChange={(event) => onTogglePageSelected(event.target.checked)}
              />
              Select visible page
            </label>
            {emails.map((email) => (
              <EmailMobileCard
                key={email.id}
                email={email}
                markReadPending={markReadPending}
                selected={selectedIds.has(email.id)}
                onMarkRead={onMarkRead}
                onToggleSelected={onToggleSelected}
              />
            ))}
          </div>

          <PaginationControls
            hasNextPage={hasNextPage}
            offset={offset}
            total={total}
            onNextPage={onNextPage}
            onPreviousPage={onPreviousPage}
          />
        </>
      ) : (
        <EmptyState
          icon="inbox"
          title="No unread emails in this view"
          description="Use the KPI cards above to switch categories, or run a fresh scan."
        />
      )}
    </section>
  );
}

interface EmailRowProps {
  readonly email: Schemas['EmailRow'];
  readonly markReadPending: boolean;
  readonly selected: boolean;
  readonly onMarkRead: (emailId: string) => void;
  readonly onToggleSelected: (emailId: string, checked: boolean) => void;
}

/**
 * Render one desktop email table row.
 *
 * @param props - Component props.
 * @returns The rendered table row.
 */
function EmailTableRow(props: EmailRowProps): JSX.Element {
  const { email, markReadPending, selected, onMarkRead, onToggleSelected } = props;
  return (
    <tr>
      <td className="px-3 py-3 align-top">
        <input
          type="checkbox"
          checked={selected}
          onChange={(event) => onToggleSelected(email.id, event.target.checked)}
          aria-label={`Select ${email.subject}`}
        />
      </td>
      <td className="px-3 py-3 align-top">
        <CategoryBadge email={email} />
      </td>
      <td className="max-w-[220px] px-3 py-3 align-top">
        <p className="truncate font-medium text-fg">{email.sender}</p>
        <p className="truncate text-xs text-fg-muted">{email.account_email}</p>
      </td>
      <td className="px-3 py-3 align-top">
        <div className="flex max-w-[var(--measure)] flex-col gap-1">
          <p className="font-medium text-fg">{email.subject}</p>
          {email.summary_excerpt ? (
            <p className="line-clamp-2 text-sm text-fg-muted">{email.summary_excerpt}</p>
          ) : null}
          <div className="flex flex-wrap items-center gap-2">
            {email.needs_review ? <Badge tone="warn">🤔 double-check</Badge> : null}
            <OpenInGmailLink accountEmail={email.account_email} threadId={email.thread_id} />
          </div>
        </div>
      </td>
      <td className="whitespace-nowrap px-3 py-3 align-top text-sm text-fg-muted">
        <time dateTime={email.received_at}>{formatReceived(email.received_at)}</time>
      </td>
      <td className="px-3 py-3 align-top">
        <Button
          variant="secondary"
          size="sm"
          onClick={() => onMarkRead(email.id)}
          disabled={markReadPending}
        >
          Mark read
        </Button>
      </td>
    </tr>
  );
}

/**
 * Render one mobile email card.
 *
 * @param props - Component props.
 * @returns The rendered card.
 */
function EmailMobileCard(props: EmailRowProps): JSX.Element {
  const { email, markReadPending, selected, onMarkRead, onToggleSelected } = props;
  return (
    <Card className="flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <label className="flex min-w-0 items-start gap-2">
          <input
            type="checkbox"
            checked={selected}
            onChange={(event) => onToggleSelected(email.id, event.target.checked)}
            aria-label={`Select ${email.subject}`}
          />
          <span className="min-w-0">
            <span className="block truncate text-sm font-semibold text-fg">{email.subject}</span>
            <span className="block truncate text-xs text-fg-muted">{email.sender}</span>
          </span>
        </label>
        <CategoryBadge email={email} />
      </div>
      {email.summary_excerpt ? (
        <p className="text-sm text-fg-muted">{email.summary_excerpt}</p>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        {email.needs_review ? <Badge tone="warn">🤔 double-check</Badge> : null}
        <span className="text-xs text-fg-muted">{formatReceived(email.received_at)}</span>
        <OpenInGmailLink accountEmail={email.account_email} threadId={email.thread_id} />
      </div>
      <Button
        variant="secondary"
        size="sm"
        onClick={() => onMarkRead(email.id)}
        disabled={markReadPending}
      >
        Mark read
      </Button>
    </Card>
  );
}

interface CategoryBadgeProps {
  readonly email: Schemas['EmailRow'];
}

/**
 * Render the row category tag.
 *
 * @param props - Component props.
 * @returns The rendered badge.
 */
function CategoryBadge(props: CategoryBadgeProps): JSX.Element {
  const meta = BUCKET_META[props.email.bucket];
  return <Badge tone={meta.tone}>{meta.label}</Badge>;
}

interface PaginationControlsProps {
  readonly hasNextPage: boolean;
  readonly offset: number;
  readonly total: number;
  readonly onNextPage: () => void;
  readonly onPreviousPage: () => void;
}

/**
 * Render offset pagination controls for the table.
 *
 * @param props - Component props.
 * @returns The rendered pagination row.
 */
function PaginationControls(props: PaginationControlsProps): JSX.Element {
  const { hasNextPage, offset, total, onNextPage, onPreviousPage } = props;
  const start = total === 0 ? 0 : offset + 1;
  const end = Math.min(total, offset + EMAIL_LIMIT);
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-fg-muted">
      <span>
        Showing {start}-{end} of {total}
      </span>
      <div className="flex items-center gap-2">
        <Button variant="secondary" size="sm" onClick={onPreviousPage} disabled={offset === 0}>
          Previous
        </Button>
        <Button variant="secondary" size="sm" onClick={onNextPage} disabled={!hasNextPage}>
          Next
        </Button>
      </div>
    </div>
  );
}

interface MarkReadStatusProps {
  readonly mutation: UseMutationResult<
    Schemas['MarkReadResponse'],
    Error,
    MarkReadVariables,
    OptimisticMarkReadContext
  >;
}

/**
 * Render mark-read success/failure feedback.
 *
 * @param props - Component props.
 * @returns The rendered status region.
 */
function MarkReadStatus(props: MarkReadStatusProps): JSX.Element | null {
  const { mutation } = props;
  if (mutation.isError) {
    return (
      <Alert tone="danger" title="Could not mark mail read">
        <p>{mutation.error.message}</p>
      </Alert>
    );
  }
  if (mutation.data && mutation.data.failed.length > 0) {
    return (
      <Alert tone="warn" title="Some messages need attention">
        <p>
          {mutation.data.marked} marked read; {mutation.data.failed.length} could not be updated.
        </p>
      </Alert>
    );
  }
  if (mutation.data && mutation.data.marked > 0) {
    return (
      <Alert tone="success" title="Marked read">
        <p>
          {mutation.data.marked} message{mutation.data.marked === 1 ? '' : 's'} cleared.
        </p>
      </Alert>
    );
  }
  return null;
}

/**
 * Format an ISO timestamp for compact table display.
 *
 * @param iso - ISO timestamp.
 * @returns Localized date/time text.
 */
function formatReceived(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}
