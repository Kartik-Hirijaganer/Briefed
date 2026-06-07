import type { Schemas } from '../../api/types';
import { type Bucket, FILTER_TABS } from '../../config/presentation';

/**
 * Props for {@link FilterTabs}.
 */
export interface FilterTabsProps {
  /** Active bucket filter, or null for "All". */
  readonly activeBucket: Bucket | null;
  /** Digest counts per bucket. */
  readonly counts: Schemas['DigestToday']['counts'];
  /** Loaded total for the active view (preferred over digest counts when set). */
  readonly activeTotal: number | undefined;
  /** Invoked with the selected bucket (or null for "All"). */
  readonly onSelect: (bucket: Bucket | null) => void;
}

interface BucketCountDisplayOptions {
  readonly bucket: Bucket;
  readonly counts: Schemas['DigestToday']['counts'];
  readonly activeBucket: Bucket | null;
  readonly activeTotal: number | undefined;
}

/**
 * Return the count for a bucket, preferring the loaded table total for the
 * currently selected bucket (so the active pill matches the list).
 *
 * @param options - Count reconciliation inputs.
 * @returns The count to render in the pill.
 */
function bucketCountForDisplay(options: BucketCountDisplayOptions): number {
  const { bucket, counts, activeBucket, activeTotal } = options;
  if (bucket === activeBucket && activeTotal !== undefined) return activeTotal;
  return counts[bucket];
}

/**
 * Horizontal pill row that filters the reader by triage bucket. Each pill is
 * a toggle `<button aria-pressed>` whose accessible name contains its label;
 * the row scrolls horizontally on narrow screens.
 *
 * @param props - Component props.
 * @returns The rendered filter pills.
 */
export function FilterTabs(props: FilterTabsProps): JSX.Element {
  const { activeBucket, counts, activeTotal, onSelect } = props;
  const allCount =
    activeBucket === null && activeTotal !== undefined
      ? activeTotal
      : counts.must_read + counts.good_to_read + counts.ignore;

  return (
    <div
      className="flex items-center gap-2 overflow-x-auto"
      role="group"
      aria-label="Filter by category"
    >
      {FILTER_TABS.map((tab) => {
        const active = activeBucket === tab.bucket;
        const count =
          tab.bucket === null
            ? allCount
            : bucketCountForDisplay({ bucket: tab.bucket, counts, activeBucket, activeTotal });
        return (
          <button
            key={tab.label}
            type="button"
            aria-pressed={active}
            onClick={() => onSelect(tab.bucket)}
            className={`inline-flex shrink-0 items-center gap-2 rounded-[var(--radius-md)] border px-3 py-1.5 text-sm font-medium duration-[var(--motion-fast)] ease-[var(--ease-standard)] ${
              active
                ? 'border-accent bg-accent/10 text-accent'
                : 'border-border text-fg-muted hover:bg-bg-muted'
            }`}
          >
            <span>{tab.label}</span>
            <span className={`text-xs ${active ? 'text-accent' : 'text-fg-faint'}`}>{count}</span>
          </button>
        );
      })}
    </div>
  );
}
