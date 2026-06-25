import { Button } from '@briefed/ui';
import { useEffect, useRef } from 'react';

/**
 * Props for {@link EmailSelectionBar}.
 */
export interface EmailSelectionBarProps {
  /** Number of visible unread rows. */
  readonly total: number;
  /** Number of checked rows. */
  readonly selectedCount: number;
  /** Whether every visible row is checked. */
  readonly allSelected: boolean;
  /** Whether the header checkbox should show the indeterminate state. */
  readonly indeterminate: boolean;
  /** Check / clear every visible row. */
  readonly onToggleAll: (checked: boolean) => void;
  /** Mark the checked rows read. */
  readonly onMarkRead: () => void;
  /** Whether the mark-read button is disabled (nothing selected / offline / pending). */
  readonly markReadDisabled: boolean;
  /** Whether a mark-read request is in flight. */
  readonly markReadLoading: boolean;
  /** Optional tooltip explaining a disabled button (e.g. offline, nothing selected). */
  readonly markReadTooltip?: string | undefined;
}

/**
 * Sticky multi-select action bar for the dashboard email list. Hosts the
 * select-all checkbox (indeterminate when partially selected), the selection
 * count, and the primary "Mark all read" / "Mark N read" action. Modeled on
 * the unsubscribe page's selection bar.
 *
 * @param props - Component props.
 * @returns The rendered selection bar.
 */
export function EmailSelectionBar(props: EmailSelectionBarProps): JSX.Element {
  const {
    total,
    selectedCount,
    allSelected,
    indeterminate,
    onToggleAll,
    onMarkRead,
    markReadDisabled,
    markReadLoading,
    markReadTooltip,
  } = props;

  const checkboxRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (checkboxRef.current) checkboxRef.current.indeterminate = indeterminate;
  }, [indeterminate]);

  const label = selectedCount > 0 && !allSelected ? `Mark ${selectedCount} read` : 'Mark all read';

  return (
    <div className="sticky top-0 z-10 flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-md)] border border-border bg-bg-canvas px-3 py-2">
      <label className="flex items-center gap-2 text-sm text-fg">
        <input
          ref={checkboxRef}
          type="checkbox"
          checked={allSelected}
          onChange={(event) => onToggleAll(event.target.checked)}
          aria-label="Select all visible emails"
        />
        <span>{selectedCount > 0 ? `${selectedCount} selected` : `${total} unread`}</span>
      </label>
      <Button
        variant="primary"
        size="sm"
        onClick={onMarkRead}
        disabled={markReadDisabled}
        loading={markReadLoading}
        title={markReadTooltip}
      >
        {label}
      </Button>
    </div>
  );
}
