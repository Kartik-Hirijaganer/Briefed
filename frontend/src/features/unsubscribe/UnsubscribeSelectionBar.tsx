import { Button } from '@briefed/ui';
import { useEffect, useRef } from 'react';

/**
 * Props for {@link UnsubscribeSelectionBar}.
 */
export interface UnsubscribeSelectionBarProps {
  /** Total displayed senders. */
  readonly total: number;
  /** Number selected. */
  readonly selectedCount: number;
  /** Whether every sender is selected. */
  readonly allSelected: boolean;
  /** Whether the header checkbox should show the indeterminate state. */
  readonly indeterminate: boolean;
  /** Select / clear every sender. */
  readonly onToggleAll: (checked: boolean) => void;
  /** Keep (dismiss) the selected senders. */
  readonly onKeep: () => void;
  /** Whether Keep is disabled (nothing selected). */
  readonly keepDisabled: boolean;
  /** Run the primary (destructive) action on the selection. */
  readonly onPrimary: () => void;
  /** Label for the primary button (e.g. "Unsubscribe 3 selected"). */
  readonly primaryLabel: string;
  /** Whether the primary action is disabled. */
  readonly primaryDisabled: boolean;
  /** Whether the primary action is in flight. */
  readonly primaryLoading: boolean;
  /** Optional tooltip explaining a disabled primary (e.g. offline). */
  readonly primaryTooltip?: string | undefined;
}

/**
 * Sticky multi-select action bar for the unsubscribe page. Hosts the
 * select-all checkbox (indeterminate when partially selected), the selection
 * count, a "Keep selected" secondary action, and the destructive primary
 * "Unsubscribe N selected" action.
 *
 * @param props - Component props.
 * @returns The rendered selection bar.
 */
export function UnsubscribeSelectionBar(props: UnsubscribeSelectionBarProps): JSX.Element {
  const {
    total,
    selectedCount,
    allSelected,
    indeterminate,
    onToggleAll,
    onKeep,
    keepDisabled,
    onPrimary,
    primaryLabel,
    primaryDisabled,
    primaryLoading,
    primaryTooltip,
  } = props;

  const checkboxRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (checkboxRef.current) checkboxRef.current.indeterminate = indeterminate;
  }, [indeterminate]);

  return (
    <div className="sticky top-0 z-10 flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-md)] border border-border bg-bg-canvas px-3 py-2">
      <label className="flex items-center gap-2 text-sm text-fg">
        <input
          ref={checkboxRef}
          type="checkbox"
          checked={allSelected}
          onChange={(event) => onToggleAll(event.target.checked)}
          aria-label="Select all senders"
        />
        <span>
          {selectedCount} of {total} selected
        </span>
      </label>
      <div className="flex items-center gap-2">
        <Button variant="secondary" size="sm" onClick={onKeep} disabled={keepDisabled}>
          Keep selected
        </Button>
        <Button
          variant="destructive"
          size="sm"
          onClick={onPrimary}
          disabled={primaryDisabled}
          loading={primaryLoading}
          title={primaryTooltip}
        >
          {primaryLabel}
        </Button>
      </div>
    </div>
  );
}
