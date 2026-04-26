import { useQuery } from '@tanstack/react-query';

import { EmptyState, ErrorState, FreshnessBadge, Skeleton } from '@briefed/ui';

import { api, unwrap } from '../api/client';
import { EmailCard } from '../features/email/EmailCard';
import { useEmailBucketMutation } from '../features/email/useEmailBucketMutation';
import { useFreshnessState } from '../hooks/useFreshnessState';
import type { Schemas } from '../api/types';

/**
 * Props for {@link TriagePage}.
 */
export interface TriagePageProps {
  /** Which bucket to display. */
  readonly bucket: Schemas['EmailRow']['bucket'];
}

const BUCKET_LABEL: Record<Schemas['EmailRow']['bucket'], string> = {
  must_read: 'Must read',
  good_to_read: 'Good to read',
  ignore: 'Ignore',
  waste: 'Waste',
};

const STALE_MS = 2 * 60 * 1000;

/**
 * Shared bucket list (`/must-read`, `/good-to-read`, `/ignore`, `/waste`).
 *
 * @param props - Page props.
 * @returns The rendered page.
 */
export default function TriagePage(props: TriagePageProps): JSX.Element {
  const { bucket } = props;
  const queryKey = ['emails', bucket];
  const bucketMutation = useEmailBucketMutation();
  const emailsQuery = useQuery({
    queryKey,
    queryFn: async () =>
      unwrap(
        await api.GET('/api/v1/emails', {
          params: { query: { bucket, limit: 50 } },
        }),
      ),
    staleTime: STALE_MS,
  });
  const freshness = useFreshnessState({ queryKey, staleTime: STALE_MS });

  return (
    <section className="flex flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-xl font-semibold tracking-tight">{BUCKET_LABEL[bucket]}</h1>
          <FreshnessBadge
            state={freshness.state}
            lastKnownGoodAt={freshness.lastKnownGoodAt ?? undefined}
          />
        </div>
        {emailsQuery.data ? (
          <span className="text-xs text-fg-muted">{emailsQuery.data.total} total</span>
        ) : null}
      </header>

      {emailsQuery.isPending ? (
        <div className="flex flex-col gap-3">
          <Skeleton shape="block" />
          <Skeleton shape="block" />
          <Skeleton shape="block" />
        </div>
      ) : emailsQuery.isError ? (
        <ErrorState
          title="Could not load emails"
          detail={emailsQuery.error instanceof Error ? emailsQuery.error.message : undefined}
        />
      ) : emailsQuery.data && emailsQuery.data.emails.length > 0 ? (
        <ul className="flex flex-col gap-3">
          {emailsQuery.data.emails.map((email) => (
            <li key={email.id}>
              <EmailCard
                email={email}
                onBucketChange={(row, nextBucket) =>
                  bucketMutation.mutate({ email: row, bucket: nextBucket })
                }
              />
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState
          icon="inbox"
          title={`Nothing in ${BUCKET_LABEL[bucket]}`}
          description="Run a scan from the dashboard to pick up new mail."
        />
      )}
    </section>
  );
}
