import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { Badge, Button, Card, EmptyState, ErrorState, FreshnessBadge, Skeleton } from '@briefed/ui';

import { api, unwrap } from '../api/client';
import { useFreshnessState } from '../hooks/useFreshnessState';

const STALE_MS = 5 * 60 * 1000;

/**
 * Jobs board (`/jobs`). Toggle between "Passed filter" and "All" plus
 * per-row confidence badge and source-email deep link.
 *
 * @returns The rendered page.
 */
export default function JobsPage(): JSX.Element {
  const [onlyPassed, setOnlyPassed] = useState(true);
  const queryKey = ['jobs', onlyPassed];

  const jobsQuery = useQuery({
    queryKey,
    queryFn: async () =>
      unwrap(
        await api.GET('/api/v1/jobs', {
          params: { query: { include_filtered: !onlyPassed } },
        }),
      ),
    staleTime: STALE_MS,
  });
  const freshness = useFreshnessState({ queryKey, staleTime: STALE_MS });

  return (
    <section className="flex flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-xl font-semibold tracking-tight">Jobs</h1>
          <FreshnessBadge
            state={freshness.state}
            lastKnownGoodAt={freshness.lastKnownGoodAt ?? undefined}
          />
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant={onlyPassed ? 'primary' : 'secondary'}
            size="sm"
            onClick={() => setOnlyPassed(true)}
          >
            Passed filter
          </Button>
          <Button
            variant={onlyPassed ? 'secondary' : 'primary'}
            size="sm"
            onClick={() => setOnlyPassed(false)}
          >
            All
          </Button>
        </div>
      </header>

      {jobsQuery.isPending ? (
        <div className="flex flex-col gap-3">
          <Skeleton shape="block" />
          <Skeleton shape="block" />
        </div>
      ) : jobsQuery.isError ? (
        <ErrorState
          title="Could not load jobs"
          detail={jobsQuery.error instanceof Error ? jobsQuery.error.message : undefined}
        />
      ) : jobsQuery.data && jobsQuery.data.matches.length > 0 ? (
        <ul className="flex flex-col gap-3">
          {jobsQuery.data.matches.map((job) => (
            <li key={job.id}>
              <Card className="flex flex-col gap-2">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h3 className="truncate text-sm font-semibold text-fg">
                      {job.title} — {job.company}
                    </h3>
                    <p className="text-xs text-fg-muted">
                      {job.location ?? 'Remote / unspecified'} ·{' '}
                      {formatCompensation(job.comp_min, job.comp_max, job.currency)}
                    </p>
                  </div>
                  <Badge tone={job.passed_filter ? 'success' : 'neutral'}>
                    {Math.round(Number(job.match_score) * 100)}%
                  </Badge>
                </div>
                <p className="text-xs text-fg-muted">{job.match_reason}</p>
                {job.source_url ? (
                  <a
                    href={job.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-accent underline-offset-4 hover:underline"
                  >
                    Open posting
                  </a>
                ) : null}
              </Card>
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState
          icon="bolt"
          title={onlyPassed ? 'No jobs passed your filter today' : 'No jobs extracted today'}
          description="Tune filters in Settings → Preferences to change what surfaces here."
        />
      )}
    </section>
  );
}

function formatCompensation(
  min: number | null,
  max: number | null,
  currency: string | null,
): string {
  if (min === null && max === null) return 'Salary n/a';
  const prefix = currency ? `${currency} ` : '';
  if (min !== null && max !== null)
    return `${prefix}${min.toLocaleString()}-${max.toLocaleString()}`;
  if (min !== null) return `${prefix}${min.toLocaleString()}+`;
  return `${prefix}${max?.toLocaleString()}`;
}
