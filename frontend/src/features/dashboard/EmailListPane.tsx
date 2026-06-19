import { Button, EmptyState, ErrorState, Motion, MOTION_PRESETS } from '@briefed/ui';
import { Inbox } from 'lucide-react';

import type { Schemas } from '../../api/types';
import { LIST_STAGGER_SECONDS, SORT_OPTIONS } from '../../config/presentation';
import { DashboardSkeletons } from './DashboardSkeletons';
import { EmailListRow } from './EmailListRow';
import { EmailSelectionBar } from './EmailSelectionBar';

/**
 * Props for {@link EmailListPane}.
 */
export interface EmailListPaneProps {
  /** Rows to render. */
  readonly emails: readonly Schemas['EmailRow'][];
  /** Active selection id. */
  readonly selectedId: string | null;
  /** Invoked when a row is chosen. */
  readonly onSelect: (emailId: string) => void;
  /** Emails query is loading. */
  readonly isPending: boolean;
  /** Emails query failed. */
  readonly isError: boolean;
  /** Emails query error. */
  readonly error: unknown;
  /** Current pagination offset. */
  readonly offset: number;
  /** Total rows in the view. */
  readonly total: number;
  /** Page size. */
  readonly pageSize: number;
  /** Whether a next page exists. */
  readonly hasNextPage: boolean;
  /** Advance one page. */
  readonly onNextPage: () => void;
  /** Go back one page. */
  readonly onPreviousPage: () => void;
  /** Set of ids checked for bulk mark-read. */
  readonly selectedIds: ReadonlySet<string>;
  /** Toggle one row's bulk-selection checkbox. */
  readonly onToggleBulk: (emailId: string, checked: boolean) => void;
  /** Number of checked rows. */
  readonly selectedCount: number;
  /** Whether every visible row is checked. */
  readonly allSelected: boolean;
  /** Whether at least one visible row is checked. */
  readonly someSelected: boolean;
  /** Check or clear every visible row. */
  readonly onToggleAll: (checked: boolean) => void;
  /** Mark the checked rows read. */
  readonly onMarkRead: () => void;
  /** Whether a mark-read request is in flight. */
  readonly markReadLoading: boolean;
  /** Live online status (mark-read is disabled offline). */
  readonly online: boolean;
}

/**
 * The left list pane: a sort caption, a staggered column of selectable
 * {@link EmailListRow}s, and offset pagination. Renders a skeleton while
 * loading, an error block on failure, and an empty state when there are no
 * rows.
 *
 * @param props - Component props.
 * @returns The rendered list pane.
 */
export function EmailListPane(props: EmailListPaneProps): JSX.Element {
  const {
    emails,
    selectedId,
    onSelect,
    isPending,
    isError,
    error,
    offset,
    total,
    pageSize,
    hasNextPage,
    onNextPage,
    onPreviousPage,
    selectedIds,
    onToggleBulk,
    selectedCount,
    allSelected,
    someSelected,
    onToggleAll,
    onMarkRead,
    markReadLoading,
    online,
  } = props;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between px-1">
        <span className="text-xs text-fg-muted">{total} unread</span>
        <span className="text-xs text-fg-faint">{SORT_OPTIONS[0]}</span>
      </div>

      {isPending ? (
        <DashboardSkeletons.ListPaneSkeleton />
      ) : isError ? (
        <ErrorState
          title="Could not load emails"
          detail={error instanceof Error ? error.message : undefined}
        />
      ) : emails.length > 0 ? (
        <>
          <EmailSelectionBar
            selectedCount={selectedCount}
            allSelected={allSelected}
            indeterminate={someSelected && !allSelected}
            onToggleAll={onToggleAll}
            onMarkRead={onMarkRead}
            markReadDisabled={selectedCount === 0 || !online || markReadLoading}
            markReadLoading={markReadLoading}
            markReadTooltip={
              !online
                ? "You're offline"
                : selectedCount === 0
                  ? 'Select emails to mark read'
                  : undefined
            }
          />
          <ul className="flex flex-col gap-1">
            {emails.map((email, index) => (
              <li key={email.id}>
                <Motion
                  pace="base"
                  {...MOTION_PRESETS.listItem}
                  transition={{ delay: index * LIST_STAGGER_SECONDS }}
                >
                  <EmailListRow
                    email={email}
                    selected={email.id === selectedId}
                    onSelect={onSelect}
                    bulkSelected={selectedIds.has(email.id)}
                    onToggleBulk={onToggleBulk}
                  />
                </Motion>
              </li>
            ))}
          </ul>
          <PaginationControls
            hasNextPage={hasNextPage}
            offset={offset}
            pageSize={pageSize}
            total={total}
            onNextPage={onNextPage}
            onPreviousPage={onPreviousPage}
          />
        </>
      ) : (
        <EmptyState
          icon={Inbox}
          title="No unread emails in this view"
          description="Switch categories above, or run a fresh scan."
        />
      )}
    </div>
  );
}

interface PaginationControlsProps {
  readonly hasNextPage: boolean;
  readonly offset: number;
  readonly pageSize: number;
  readonly total: number;
  readonly onNextPage: () => void;
  readonly onPreviousPage: () => void;
}

/**
 * Offset pagination controls for the list pane (logic unchanged from the
 * previous table implementation).
 *
 * @param props - Component props.
 * @returns The rendered pagination row.
 */
function PaginationControls(props: PaginationControlsProps): JSX.Element {
  const { hasNextPage, offset, pageSize, total, onNextPage, onPreviousPage } = props;
  const start = total === 0 ? 0 : offset + 1;
  const end = Math.min(total, offset + pageSize);
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-fg-muted">
      <span>
        Showing {start}-{end} of {total}
      </span>
      <div className="flex items-center gap-2">
        <Button variant="secondary" size="sm" onClick={onPreviousPage} disabled={offset === 0}>
          Previous
        </Button>
        <Button variant="secondary" size="sm" onClick={onNextPage} disabled={!hasNextPage}>
          Next
        </Button>
      </div>
    </div>
  );
}
