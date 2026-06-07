import { Skeleton } from '@briefed/ui';

import { SKELETON_COUNTS } from '../../config/presentation';

/**
 * Loading placeholder for the overview band (title + filter pills).
 *
 * @returns The rendered skeleton.
 */
function OverviewBandSkeleton(): JSX.Element {
  return (
    <div className="flex flex-col gap-4">
      <Skeleton shape="line" width="12rem" />
      <div className="flex gap-2">
        {Array.from({ length: 4 }, (_, index) => (
          <Skeleton key={`band-pill-${index}`} shape="pill" />
        ))}
      </div>
    </div>
  );
}

/**
 * Loading placeholder for the list pane — one block per expected row.
 *
 * @returns The rendered skeleton.
 */
function ListPaneSkeleton(): JSX.Element {
  return (
    <div className="flex flex-col gap-2">
      {Array.from({ length: SKELETON_COUNTS.emails }, (_, index) => (
        <Skeleton key={`list-row-${index}`} shape="block" height="3.5rem" />
      ))}
    </div>
  );
}

/**
 * Loading placeholder for the reading pane (header + body lines).
 *
 * @returns The rendered skeleton.
 */
function ReadingPaneSkeleton(): JSX.Element {
  return (
    <div className="flex flex-col gap-4 rounded-[var(--radius-lg)] border border-border bg-surface p-5">
      <Skeleton shape="pill" />
      <div className="flex items-start gap-3">
        <Skeleton shape="avatar" />
        <div className="flex flex-1 flex-col gap-2">
          <Skeleton shape="line" width="70%" />
          <Skeleton shape="line" width="40%" />
        </div>
      </div>
      <Skeleton shape="block" />
      <Skeleton shape="line" />
      <Skeleton shape="line" width="90%" />
    </div>
  );
}

/**
 * The dashboard loading-state skeletons, grouped for a single import.
 */
export const DashboardSkeletons = {
  OverviewBandSkeleton,
  ListPaneSkeleton,
  ReadingPaneSkeleton,
} as const;
