import { useQuery } from '@tanstack/react-query';

import { Card, EmptyState, ErrorState, FreshnessBadge, Skeleton } from '@briefed/ui';

import { api, unwrap } from '../api/client';
import { useFreshnessState } from '../hooks/useFreshnessState';

const STALE_MS = 5 * 60 * 1000;

/**
 * Tech news digest (`/news`). Groups newsletters into clusters produced
 * by the summarization stage (plan §6 pipeline).
 *
 * @returns The rendered page.
 */
export default function NewsPage(): JSX.Element {
  const newsQuery = useQuery({
    queryKey: ['news'],
    queryFn: async () => unwrap(await api.GET('/api/v1/news')),
    staleTime: STALE_MS,
  });
  const freshness = useFreshnessState({ queryKey: ['news'], staleTime: STALE_MS });

  return (
    <section className="flex flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-xl font-semibold tracking-tight">Tech news digest</h1>
          <FreshnessBadge
            state={freshness.state}
            lastKnownGoodAt={freshness.lastKnownGoodAt ?? undefined}
          />
        </div>
      </header>

      {newsQuery.isPending ? (
        <div className="flex flex-col gap-3">
          <Skeleton shape="block" />
          <Skeleton shape="block" />
        </div>
      ) : newsQuery.isError ? (
        <ErrorState
          title="Could not load news digest"
          detail={newsQuery.error instanceof Error ? newsQuery.error.message : undefined}
        />
      ) : newsQuery.data && newsQuery.data.clusters.length > 0 ? (
        <ul className="flex flex-col gap-3">
          {newsQuery.data.clusters.map((cluster) => (
            <li key={cluster.id}>
              <Card className="flex flex-col gap-2">
                <h2 className="text-base font-semibold text-fg">{cluster.label}</h2>
                <p className="whitespace-pre-wrap text-sm text-fg-muted">{cluster.summary_md}</p>
                <span className="text-xs text-fg-muted">
                  Clustered from {cluster.email_ids.length} emails
                </span>
              </Card>
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState
          icon="inbox"
          title="No news digests yet"
          description="Newsletter summaries land here after the next daily run."
        />
      )}
    </section>
  );
}
