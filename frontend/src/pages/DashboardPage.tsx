import { useQuery } from '@tanstack/react-query';

import { Alert, Card, EmptyState, ErrorState, FreshnessBadge, Skeleton } from '@briefed/ui';

import { api, unwrap } from '../api/client';
import { EmailCard } from '../features/email/EmailCard';
import { ScanNowButton } from '../features/dashboard/ScanNowButton';
import { useFreshnessState } from '../hooks/useFreshnessState';

const DIGEST_STALE_MS = 60 * 1000;

/**
 * Dashboard page (`/`). Top-level daily digest summary with must-read
 * preview, cost today, and the Scan Now trigger per plan §19.16 §3.
 *
 * @returns The rendered page.
 */
export default function DashboardPage(): JSX.Element {
  const digestQuery = useQuery({
    queryKey: ['digest-today'],
    queryFn: async () => unwrap(await api.GET('/api/v1/digest/today')),
    staleTime: DIGEST_STALE_MS,
  });
  const freshness = useFreshnessState({
    queryKey: ['digest-today'],
    staleTime: DIGEST_STALE_MS,
  });

  const lastRunAt = digestQuery.data?.last_successful_run_at ?? null;
  const hoursSinceLastRun = lastRunAt
    ? (Date.now() - new Date(lastRunAt).getTime()) / (60 * 60 * 1000)
    : Infinity;

  return (
    <section className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-semibold tracking-tight">Today&apos;s Digest</h1>
          <FreshnessBadge
            state={freshness.state}
            lastKnownGoodAt={freshness.lastKnownGoodAt ?? undefined}
          />
        </div>
        <ScanNowButton />
      </header>

      {hoursSinceLastRun > 24 * 7 ? (
        <Alert tone="warn" title="Auto-scan may be off">
          <p>It has been more than 7 days since the last successful scan. Run a manual scan or
            re-enable auto-scans in settings.</p>
        </Alert>
      ) : null}

      {digestQuery.isPending ? (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Skeleton shape="block" />
          <Skeleton shape="block" />
          <Skeleton shape="block" />
          <Skeleton shape="block" />
        </div>
      ) : digestQuery.isError ? (
        <ErrorState
          title="Could not load today's digest"
          detail={digestQuery.error instanceof Error ? digestQuery.error.message : undefined}
        />
      ) : digestQuery.data ? (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatTile label="Must read" value={digestQuery.data.counts.must_read} tone="accent" />
            <StatTile label="Good to read" value={digestQuery.data.counts.good_to_read} />
            <StatTile label="Ignore" value={digestQuery.data.counts.ignore} />
            <StatTile
              label="Today's cost"
              value={`$${(digestQuery.data.cost_cents_today / 100).toFixed(2)}`}
              tone="neutral"
            />
          </div>

          <div className="flex flex-col gap-3">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-fg-muted">
              Must-read preview
            </h2>
            {digestQuery.data.must_read_preview.length === 0 ? (
              <EmptyState
                icon="check"
                title="Inbox zero for today"
                description="Nothing urgent landed since the last scan."
              />
            ) : (
              digestQuery.data.must_read_preview.map((email) => (
                <EmailCard key={email.id} email={email} />
              ))
            )}
          </div>
        </>
      ) : null}
    </section>
  );
}

interface StatTileProps {
  readonly label: string;
  readonly value: number | string;
  readonly tone?: 'accent' | 'neutral';
}

/**
 * Small stat tile rendered inside the Dashboard header grid.
 *
 * @param props - Tile props.
 * @returns The rendered tile.
 */
function StatTile(props: StatTileProps): JSX.Element {
  const { label, value, tone } = props;
  return (
    <Card>
      <div className="flex flex-col gap-1">
        <span className="text-xs uppercase tracking-wide text-fg-muted">{label}</span>
        <span
          className={`text-2xl font-semibold ${tone === 'accent' ? 'text-accent' : 'text-fg'}`}
        >
          {value}
        </span>
      </div>
    </Card>
  );
}
