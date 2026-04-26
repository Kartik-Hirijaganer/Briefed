import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';

import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  FreshnessBadge,
  Skeleton,
  type BadgeTone,
} from '@briefed/ui';

import { api, unwrap } from '../api/client';
import { useFreshnessState } from '../hooks/useFreshnessState';

const STALE_MS = 60 * 1000;

const STATUS_TONE: Record<string, BadgeTone> = {
  complete: 'success',
  running: 'accent',
  queued: 'neutral',
  failed: 'danger',
};

/**
 * Run history (`/history`). Detail drilldown is a follow-up Phase 7 surface;
 * today we list rows so operators can eyeball cost + outcome.
 *
 * @returns The rendered page.
 */
export default function HistoryPage(): JSX.Element {
  const runsQuery = useQuery({
    queryKey: ['history'],
    queryFn: async () => unwrap(await api.GET('/api/v1/history')),
    staleTime: STALE_MS,
  });
  const freshness = useFreshnessState({ queryKey: ['history'], staleTime: STALE_MS });

  return (
    <section className="flex flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-xl font-semibold tracking-tight">Run history</h1>
          <FreshnessBadge
            state={freshness.state}
            lastKnownGoodAt={freshness.lastKnownGoodAt ?? undefined}
          />
        </div>
      </header>

      {runsQuery.isPending ? (
        <Skeleton shape="block" />
      ) : runsQuery.isError ? (
        <ErrorState
          title="Could not load history"
          detail={runsQuery.error instanceof Error ? runsQuery.error.message : undefined}
        />
      ) : runsQuery.data && runsQuery.data.runs.length > 0 ? (
        <ul className="flex flex-col gap-3">
          {runsQuery.data.runs.map((run) => (
            <li key={run.id}>
              <Link
                to={`/history/${run.id}`}
                className="block rounded-[var(--radius-md)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)]"
              >
                <Card className="flex flex-col gap-2">
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex flex-col">
                      <span className="text-sm font-medium text-fg">
                        {new Date(run.started_at).toLocaleString()}
                      </span>
                      <span className="text-xs text-fg-muted">{run.trigger_type}</span>
                    </div>
                    <Badge tone={STATUS_TONE[run.status] ?? 'neutral'}>{run.status}</Badge>
                  </div>
                  <div className="flex gap-4 text-xs text-fg-muted">
                    <span>Ingested {run.stats?.ingested ?? 0}</span>
                    <span>Classified {run.stats?.classified ?? 0}</span>
                    <span>Summarized {run.stats?.summarized ?? 0}</span>
                    {run.cost_cents !== undefined && run.cost_cents !== null ? (
                      <span>${(run.cost_cents / 100).toFixed(2)}</span>
                    ) : null}
                  </div>
                  {run.error ? (
                    <p className="text-xs text-danger" role="alert">
                      {run.error}
                    </p>
                  ) : null}
                </Card>
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState
          icon="inbox"
          title="No runs yet"
          description="Auto-scans and manual triggers both land here with their cost breakdown."
        />
      )}
    </section>
  );
}
