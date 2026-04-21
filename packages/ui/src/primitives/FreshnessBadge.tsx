import { Badge, type BadgeTone } from './Badge';

/**
 * Four named freshness states — plan §19.8.
 */
export type FreshnessState = 'fresh' | 'stale' | 'offline' | 'sync_failed';

/**
 * Props for {@link FreshnessBadge}.
 */
export interface FreshnessBadgeProps {
  /** Current freshness state. */
  readonly state: FreshnessState;
  /** Optional timestamp rendered alongside the badge. */
  readonly lastKnownGoodAt?: string;
}

const STATE_LABEL: Record<FreshnessState, string> = {
  fresh: 'Fresh',
  stale: 'Stale',
  offline: 'Offline',
  sync_failed: 'Sync Failed',
};

const STATE_TONE: Record<FreshnessState, BadgeTone> = {
  fresh: 'success',
  stale: 'warn',
  offline: 'neutral',
  sync_failed: 'danger',
};

/**
 * Shows one of the four plan §19.8 freshness states plus an optional
 * last-known-good timestamp. Enforced by lint on every data-bearing view.
 *
 * @param props - Component props.
 * @returns The rendered freshness badge.
 */
export function FreshnessBadge(props: FreshnessBadgeProps): JSX.Element {
  const { state, lastKnownGoodAt } = props;
  const tooltip = lastKnownGoodAt ? `Last known good: ${lastKnownGoodAt}` : undefined;
  return (
    <span title={tooltip} className="inline-flex items-center gap-2">
      <Badge tone={STATE_TONE[state]} ariaLabel={`Data freshness: ${STATE_LABEL[state]}`}>
        {STATE_LABEL[state]}
      </Badge>
    </span>
  );
}
