import { useQuery } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';

import { Badge, Button, Card, ErrorState, Skeleton, type BadgeTone } from '@briefed/ui';

import { api, unwrap } from '../api/client';
import type { Schemas } from '../api/types';

const STATUS_TONE: Record<string, BadgeTone> = {
  complete: 'success',
  running: 'accent',
  queued: 'neutral',
  failed: 'danger',
};

interface StageRow {
  readonly key: string;
  readonly label: string;
  readonly count: number;
}

/**
 * Drilldown for a single digest run (`/history/:runId`). Per plan §10 IA the
 * detail surface shows the stage timeline and cost breakdown for the run.
 *
 * @returns The rendered detail page.
 */
export default function HistoryRunDetailPage(): JSX.Element {
  const { runId } = useParams<{ runId: string }>();
  const runQuery = useQuery({
    queryKey: ['run', runId],
    queryFn: async () =>
      unwrap(await api.GET('/api/v1/runs/{run_id}', { params: { path: { run_id: runId ?? '' } } })),
    enabled: Boolean(runId),
  });

  if (!runId) {
    return (
      <ErrorState
        title="Missing run id"
        detail="Open this page from the history list so the run id is in the URL."
      />
    );
  }

  if (runQuery.isPending) return <Skeleton shape="block" />;
  if (runQuery.isError) {
    return (
      <ErrorState
        title="Could not load run"
        detail={runQuery.error instanceof Error ? runQuery.error.message : undefined}
      />
    );
  }
  const run = runQuery.data;
  if (!run) return <Skeleton shape="block" />;

  const stages = stagesFromRun(run);
  const cost = run.cost_cents ?? null;
  const completedLabel = run.completed_at
    ? new Date(run.completed_at).toLocaleString()
    : 'In progress';

  return (
    <section className="flex flex-col gap-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Button variant="link" href="/history">
            ← Back to history
          </Button>
          <h1 className="mt-1 text-xl font-semibold tracking-tight">Run {run.id.slice(0, 8)}</h1>
          <p className="text-xs text-fg-muted">
            {run.trigger_type} · started {new Date(run.started_at).toLocaleString()} · finished{' '}
            {completedLabel}
          </p>
        </div>
        <Badge tone={STATUS_TONE[run.status] ?? 'neutral'}>{run.status}</Badge>
      </header>

      <Card>
        <h2 className="text-sm font-semibold text-fg">Stage timeline</h2>
        <ol className="mt-3 flex flex-col gap-2">
          {stages.map((stage) => (
            <li
              key={stage.key}
              className="flex items-center justify-between rounded-[var(--radius-sm)] border border-border px-3 py-2"
            >
              <span className="text-sm text-fg">{stage.label}</span>
              <Badge tone="neutral">{stage.count}</Badge>
            </li>
          ))}
        </ol>
      </Card>

      <Card>
        <h2 className="text-sm font-semibold text-fg">Cost breakdown</h2>
        <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
          <dt className="text-fg-muted">LLM spend</dt>
          <dd className="text-fg">{cost === null ? 'n/a' : `$${(cost / 100).toFixed(2)}`}</dd>
          <dt className="text-fg-muted">New must-read</dt>
          <dd className="text-fg">{run.stats?.new_must_read ?? 0}</dd>
        </dl>
      </Card>

      {run.error ? (
        <Card className="border-danger/40 bg-danger/5">
          <h2 className="text-sm font-semibold text-danger">Error</h2>
          <p className="mt-2 text-sm text-fg">{run.error}</p>
        </Card>
      ) : null}

      <p className="text-xs text-fg-muted">
        <Link to="/history" className="text-accent underline-offset-4 hover:underline">
          Browse other runs
        </Link>
      </p>
    </section>
  );
}

function stagesFromRun(run: Schemas['RunStatus']): readonly StageRow[] {
  const stats = run.stats ?? { ingested: 0, classified: 0, summarized: 0, new_must_read: 0 };
  return [
    { key: 'ingested', label: 'Ingested', count: stats.ingested ?? 0 },
    { key: 'classified', label: 'Classified', count: stats.classified ?? 0 },
    { key: 'summarized', label: 'Summarized', count: stats.summarized ?? 0 },
    { key: 'new_must_read', label: 'New must-read', count: stats.new_must_read ?? 0 },
  ];
}
