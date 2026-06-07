import { FreshnessBadge, type FreshnessState } from '@briefed/ui';

import type { Schemas } from '../../api/types';
import { type Bucket, formatReceivedRelative } from '../../config/presentation';
import { FilterTabs } from './FilterTabs';
import { ScanNowButton } from './ScanNowButton';

/**
 * Props for {@link DigestOverviewBand}.
 */
export interface DigestOverviewBandProps {
  /** Today's digest payload. */
  readonly digest: Schemas['DigestToday'];
  /** Freshness state for the digest. */
  readonly freshnessState: FreshnessState;
  /** Last-known-good timestamp for the freshness badge. */
  readonly freshnessLastKnownGoodAt: string | null;
  /** Last successful run timestamp (drives the "Synced …" caption). */
  readonly lastRunAt: string | null;
  /** Active bucket filter, or null for "All". */
  readonly activeBucket: Bucket | null;
  /** Loaded total for the active view. */
  readonly activeTotal: number | undefined;
  /** Switch the active bucket filter. */
  readonly onSelectBucket: (bucket: Bucket | null) => void;
}

/**
 * Top band of the dashboard: page title, freshness badge, a "Synced … · $cost"
 * caption, the category filter pills, and the Scan-now control.
 *
 * @param props - Component props.
 * @returns The rendered overview band.
 */
export function DigestOverviewBand(props: DigestOverviewBandProps): JSX.Element {
  const {
    digest,
    freshnessState,
    freshnessLastKnownGoodAt,
    lastRunAt,
    activeBucket,
    activeTotal,
    onSelectBucket,
  } = props;

  const relative = lastRunAt ? formatReceivedRelative(lastRunAt) : null;
  const syncedText = relative
    ? relative === 'just now'
      ? 'Synced just now'
      : `Synced ${relative} ago`
    : 'Not yet synced';
  const cost = `$${(digest.cost_cents_today / 100).toFixed(2)}`;

  return (
    <header className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="font-display text-2xl font-semibold tracking-tight">
            Today&apos;s Digest
          </h1>
          <div className="flex flex-wrap items-center gap-3 text-xs text-fg-muted">
            <FreshnessBadge
              state={freshnessState}
              lastKnownGoodAt={lastRunAt ?? freshnessLastKnownGoodAt ?? undefined}
            />
            <span>
              {syncedText} · {cost}
            </span>
          </div>
        </div>
        <ScanNowButton />
      </div>
      <FilterTabs
        activeBucket={activeBucket}
        counts={digest.counts}
        activeTotal={activeTotal}
        onSelect={onSelectBucket}
      />
    </header>
  );
}
