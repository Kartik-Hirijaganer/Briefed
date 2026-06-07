import { ChevronLeft } from 'lucide-react';

import { useBreakpoint } from '../../hooks/useBreakpoint';
import { EmailListPane } from './EmailListPane';
import { ReadingPane } from './ReadingPane';
import type { DashboardData } from './useDashboardData';

/**
 * Props for {@link EmailReader}.
 */
export interface EmailReaderProps {
  /** The dashboard data + actions bundle. */
  readonly data: DashboardData;
}

/**
 * Two-pane reader. On desktop it lays the list and reading pane side by side
 * (`1fr` / `2fr`); below `md` it shows the list alone until a row is tapped,
 * then swaps to a full-width reading pane with a sticky "Back" affordance.
 *
 * @param props - Component props.
 * @returns The rendered reader.
 */
export function EmailReader(props: EmailReaderProps): JSX.Element {
  const { data } = props;
  const isMobile = useBreakpoint() === 'sm';

  const listPane = (
    <EmailListPane
      emails={data.emails}
      selectedId={data.selectedId}
      onSelect={data.setSelectedId}
      isPending={data.emailsIsPending}
      isError={data.emailsIsError}
      error={data.emailsError}
      offset={data.offset}
      total={data.totalEmails}
      pageSize={data.pageSize}
      hasNextPage={data.hasNextPage}
      onNextPage={() => data.setOffset(data.offset + data.pageSize)}
      onPreviousPage={() => data.setOffset(Math.max(0, data.offset - data.pageSize))}
    />
  );
  const readingPane = (
    <ReadingPane
      email={data.selectedEmail}
      isPending={data.emailsIsPending}
      onMarkRead={data.markOneRead}
      markReadPending={data.markRead.isPending}
      hasNextMustRead={data.hasNextMustRead}
      onNextMustRead={data.selectNextMustRead}
    />
  );

  if (isMobile) {
    if (data.hasExplicitSelection) {
      return (
        <div className="flex flex-col gap-3">
          <button
            type="button"
            onClick={() => data.setSelectedId(null)}
            aria-label="Back to list"
            className="sticky top-0 z-10 inline-flex items-center gap-1 self-start rounded-[var(--radius-md)] bg-bg-canvas px-2 py-1 text-sm font-medium text-fg-muted hover:bg-bg-muted"
          >
            <ChevronLeft aria-hidden="true" className="h-4 w-4" strokeWidth={1.75} />
            <span>Back</span>
          </button>
          {readingPane}
        </div>
      );
    }
    return listPane;
  }

  return (
    <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
      {listPane}
      {readingPane}
    </div>
  );
}
