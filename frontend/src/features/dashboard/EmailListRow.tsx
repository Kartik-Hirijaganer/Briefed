import type { Schemas } from '../../api/types';
import { formatReceivedRelative } from '../../config/presentation';

/**
 * Props for {@link EmailListRow}.
 */
export interface EmailListRowProps {
  /** The email to render. */
  readonly email: Schemas['EmailRow'];
  /** Whether this row is the active selection. */
  readonly selected: boolean;
  /** Invoked with the email id when the row is chosen. */
  readonly onSelect: (emailId: string) => void;
}

/**
 * One selectable row in the list pane. Renders an accent unread dot, the
 * sender (bold, truncated), a right-aligned relative time, and a one-line
 * subject. The whole row is a toggle button with `aria-pressed` +
 * `aria-current`; the active row gets the accent tint + left rule.
 *
 * @param props - Component props.
 * @returns The rendered row button.
 */
export function EmailListRow(props: EmailListRowProps): JSX.Element {
  const { email, selected, onSelect } = props;
  return (
    <button
      type="button"
      aria-pressed={selected}
      aria-current={selected ? 'true' : undefined}
      onClick={() => onSelect(email.id)}
      className={`flex w-full flex-col gap-1 rounded-[var(--radius-md)] border-l-2 px-3 py-2 text-left duration-[var(--motion-fast)] ease-[var(--ease-standard)] ${
        selected
          ? 'border-accent bg-accent/10 text-accent'
          : 'border-transparent text-fg hover:bg-bg-muted'
      }`}
    >
      <span className="flex items-center justify-between gap-2">
        <span className="flex min-w-0 items-center gap-2">
          <span aria-hidden="true" className="h-2 w-2 shrink-0 rounded-full bg-accent" />
          <span className="truncate font-semibold">{email.sender}</span>
        </span>
        <time dateTime={email.received_at} className="shrink-0 text-xs text-fg-faint">
          {formatReceivedRelative(email.received_at)}
        </time>
      </span>
      <span className={`truncate text-sm ${selected ? 'text-accent/80' : 'text-fg-muted'}`}>
        {email.subject}
      </span>
    </button>
  );
}
