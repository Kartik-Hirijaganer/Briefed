import { Alert, ErrorState } from '@briefed/ui';

import { DashboardSkeletons } from '../features/dashboard/DashboardSkeletons';
import { DigestOverviewBand } from '../features/dashboard/DigestOverviewBand';
import { EmailReader } from '../features/dashboard/EmailReader';
import { MarkReadStatus } from '../features/dashboard/MarkReadStatus';
import { useDashboardData } from '../features/dashboard/useDashboardData';

/**
 * Dashboard page (`/`). Thin route shell: it pulls the digest + email state
 * from {@link useDashboardData} and composes the overview band, the two-pane
 * reader, and the mark-read status feedback. All behavior lives in the
 * `features/dashboard` modules.
 *
 * @returns The rendered page.
 */
export default function DashboardPage(): JSX.Element {
  const data = useDashboardData();

  return (
    <section className="flex flex-col gap-6" {...data.pullToRefresh}>
      {data.digestIsPending ? (
        <DashboardSkeletons.OverviewBandSkeleton />
      ) : data.digestIsError ? (
        <ErrorState
          title="Could not load today's digest"
          detail={data.digestError instanceof Error ? data.digestError.message : undefined}
        />
      ) : data.digest ? (
        <>
          <DigestOverviewBand
            digest={data.digest}
            freshnessState={data.freshnessState}
            freshnessLastKnownGoodAt={data.freshnessLastKnownGoodAt}
            lastRunAt={data.lastRunAt}
            activeBucket={data.activeBucket}
            activeTotal={data.totalEmails}
            onSelectBucket={data.setBucket}
          />

          {data.autoScanMayBeOff ? (
            <Alert tone="warn" title="Auto-scan may be off">
              <p>
                It has been more than 7 days since the last successful scan. Run a manual scan or
                re-enable auto-scans in settings.
              </p>
            </Alert>
          ) : null}

          <EmailReader data={data} />

          <MarkReadStatus mutation={data.markRead} reconnectReturnTo={data.reconnectReturnTo} />
        </>
      ) : null}
    </section>
  );
}
