import { useId, type KeyboardEvent } from 'react';

/**
 * Props for {@link Switch}.
 */
export interface SwitchProps {
  /** Current on/off state. */
  readonly checked: boolean;
  /** Invoked with the next value when the user toggles. */
  readonly onCheckedChange: (next: boolean) => void;
  /** Disable interactivity. */
  readonly disabled?: boolean;
  /** Accessible label — required when no `<label>` wraps the switch. */
  readonly ariaLabel?: string;
  /** Pointer to an element containing the accessible label. */
  readonly ariaLabelledBy?: string;
}

/**
 * Accessible on/off toggle following the WAI-ARIA `switch` pattern.
 * Touch target is 52×32 with a 44×44 tappable row per §19.16.
 *
 * @param props - Component props.
 * @returns The rendered switch element.
 */
export function Switch(props: SwitchProps): JSX.Element {
  const { checked, onCheckedChange, disabled, ariaLabel, ariaLabelledBy } = props;
  const id = useId();
  const toggle = (): void => {
    if (!disabled) onCheckedChange(!checked);
  };
  const handleKey = (event: KeyboardEvent<HTMLButtonElement>): void => {
    if (event.key === ' ' || event.key === 'Enter') {
      event.preventDefault();
      toggle();
    }
  };
  const trackColor = checked ? 'bg-accent' : 'bg-border';
  const thumbX = checked ? 'translate-x-5' : 'translate-x-0.5';
  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      aria-labelledby={ariaLabelledBy}
      disabled={disabled}
      onClick={toggle}
      onKeyDown={handleKey}
      className={`relative inline-flex h-8 w-[52px] shrink-0 items-center rounded-full transition-colors duration-[var(--motion-base)] ${trackColor} disabled:opacity-50`}
    >
      <span
        aria-hidden="true"
        className={`inline-block h-7 w-7 rounded-full bg-bg-surface shadow transform transition-transform duration-[var(--motion-base)] ${thumbX}`}
      />
    </button>
  );
}
