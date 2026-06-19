import type { Schemas } from '../../api/types';
import { formatReceivedRelative } from '../../config/presentation';

/**
 * Props for {@link EmailListRow}.
 */
export interface EmailListRowProps {
  /** The email to render. */
  readonly email: Schemas['EmailRow'];
  /** Whether this row is the active reader selection. */
  readonly selected: boolean;
  /** Invoked with the email id when the row body is chosen (opens the reader). */
  readonly onSelect: (emailId: string) => void;
  /** Whether this row is checked for bulk mark-read. */
  readonly bulkSelected: boolean;
  /** Toggle this row's bulk-selection checkbox. */
  readonly onToggleBulk: (emailId: string, checked: boolean) => void;
}

/**
 * One row in the list pane: a bulk-selection checkbox followed by the row body.
 * The body button renders an accent unread dot, the sender (bold, truncated), a
 * right-aligned relative time, and a one-line subject; it carries `aria-pressed`
 * + `aria-current` and gets the accent tint + left rule when it is the active
 * reader selection. The checkbox and body are independent sibling controls —
 * checking a row never opens it in the reader, and vice versa.
 *
 * @param props - Component props.
 * @returns The rendered row.
 */
export function EmailListRow(props: EmailListRowProps): JSX.Element {
  const { email, selected, onSelect, bulkSelected, onToggleBulk } = props;
  return (
    <div className="flex items-center gap-2">
      <input
        type="checkbox"
        checked={bulkSelected}
        onChange={(event) => onToggleBulk(email.id, event.target.checked)}
        aria-label={`Select email from ${email.sender}: ${email.subject}`}
        className="shrink-0"
      />
      <button
        type="button"
        aria-pressed={selected}
        aria-current={selected ? 'true' : undefined}
        onClick={() => onSelect(email.id)}
        className={`flex min-w-0 flex-1 flex-col gap-1 rounded-[var(--radius-md)] border-l-2 px-3 py-2 text-left duration-[var(--motion-fast)] ease-[var(--ease-standard)] ${
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
    </div>
  );
}
