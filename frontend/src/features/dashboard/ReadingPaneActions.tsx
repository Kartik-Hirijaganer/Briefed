import { Button, OpenInGmailLink } from '@briefed/ui';
import { ArrowDown } from 'lucide-react';
import { Link } from 'react-router-dom';

import type { Schemas } from '../../api/types';

/**
 * Props for {@link ReadingPaneActions}.
 */
export interface ReadingPaneActionsProps {
  /** The selected email being acted on. */
  readonly email: Schemas['EmailRow'];
  /** Mark this email read (advances selection). */
  readonly onMarkRead: (emailId: string) => void;
  /** Whether a mark-read request is in flight. */
  readonly markReadPending: boolean;
  /** Whether a later must-read row exists. */
  readonly hasNextMustRead: boolean;
  /** Advance the selection to the next must-read row. */
  readonly onNextMustRead: () => void;
  /** Live online status (mark-read is disabled offline). */
  readonly online: boolean;
}

/**
 * Action row for the reading pane: the primary Mark-read button, the
 * Open-in-Gmail deep link, an Unsubscribe link to the hygiene page, and a
 * "Next must-read" jump shown only when one exists.
 *
 * @param props - Component props.
 * @returns The rendered action row.
 */
export function ReadingPaneActions(props: ReadingPaneActionsProps): JSX.Element {
  const { email, onMarkRead, markReadPending, hasNextMustRead, onNextMustRead, online } = props;
  return (
    <div className="flex flex-wrap items-center gap-3">
      <Button
        variant="primary"
        size="sm"
        loading={markReadPending}
        disabled={!online}
        title={online ? undefined : "You're offline"}
        onClick={() => onMarkRead(email.id)}
      >
        Mark read
      </Button>
      <OpenInGmailLink accountEmail={email.account_email} threadId={email.thread_id} />
      <Link to="/unsubscribe" className="text-xs text-link underline-offset-4 hover:underline">
        Unsubscribe
      </Link>
      {hasNextMustRead ? (
        <button
          type="button"
          onClick={onNextMustRead}
          className="ml-auto inline-flex items-center gap-1 text-xs font-medium text-accent underline-offset-4 hover:underline"
        >
          <span>Next must-read</span>
          <ArrowDown aria-hidden="true" className="h-3 w-3" strokeWidth={1.75} />
        </button>
      ) : null}
    </div>
  );
}
