import { Skeleton } from '@briefed/ui';

import { SKELETON_COUNTS } from '../../config/presentation';

/**
 * Card-shaped loading placeholders for the unsubscribe list — one per expected
 * sender row.
 *
 * @returns The rendered skeletons.
 */
export function SenderCardSkeleton(): JSX.Element {
  return (
    <div className="flex flex-col gap-3">
      {Array.from({ length: SKELETON_COUNTS.senders }, (_, index) => (
        <div
          key={`sender-skel-${index}`}
          className="rounded-[var(--radius-lg)] border border-border bg-surface p-4"
        >
          <div className="flex items-start gap-3">
            <Skeleton shape="avatar" />
            <div className="flex flex-1 flex-col gap-2">
              <Skeleton shape="line" width="50%" />
              <Skeleton shape="line" width="30%" />
              <Skeleton shape="pill" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
