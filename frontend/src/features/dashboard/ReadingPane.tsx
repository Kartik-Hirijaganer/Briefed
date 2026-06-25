import {
  Badge,
  Motion,
  MOTION_PRESETS,
  OpenInGmailLink,
  SafeMarkdown,
  WhySortedBanner,
} from '@briefed/ui';

import type { Schemas } from '../../api/types';
import {
  BUCKET_META,
  formatReceivedLong,
  KEYBOARD_HINT,
  SORTED_BY_LABEL,
} from '../../config/presentation';
import { DashboardSkeletons } from './DashboardSkeletons';
import { ReadingPaneActions } from './ReadingPaneActions';

/**
 * Props for {@link ReadingPane}.
 */
export interface ReadingPaneProps {
  /** The selected email, or undefined when none is selectable. */
  readonly email: Schemas['EmailRow'] | undefined;
  /** Emails query is loading (drives the skeleton). */
  readonly isPending: boolean;
  /** Mark the selected email read. */
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
 * Right-hand reading pane for the selected email. Shows the category pill, the
 * "sorted by" source, the subject + sender header with an initials avatar, the
 * always-visible why-sorted banner, the summary excerpt (as the lead) followed
 * by an Open-in-Gmail preview callout, and the action row.
 *
 * Renders a skeleton only while the emails query is pending; never fabricates
 * permanent placeholder bars.
 *
 * @param props - Component props.
 * @returns The rendered reading pane.
 */
export function ReadingPane(props: ReadingPaneProps): JSX.Element {
  const { email, isPending, onMarkRead, markReadPending, hasNextMustRead, onNextMustRead, online } =
    props;

  if (isPending) return <DashboardSkeletons.ReadingPaneSkeleton />;
  if (!email) {
    return (
      <div className="flex min-h-[12rem] items-center justify-center rounded-[var(--radius-lg)] border border-dashed border-border p-8 text-center text-sm text-fg-muted">
        {KEYBOARD_HINT}
      </div>
    );
  }

  const meta = BUCKET_META[email.bucket];

  return (
    <Motion
      key={email.id}
      pace="base"
      {...MOTION_PRESETS.fadeIn}
      className="flex flex-col gap-4 rounded-[var(--radius-lg)] border border-border bg-surface p-5"
    >
      <div className="flex items-center justify-between gap-3">
        <Badge tone={meta.tone}>{meta.label}</Badge>
        <span className="text-xs text-fg-muted">{SORTED_BY_LABEL[email.decision_source]}</span>
      </div>

      <div className="flex items-start gap-3">
        <span
          aria-hidden="true"
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-accent/10 text-sm font-semibold text-accent"
        >
          {initialsFromSender(email.sender)}
        </span>
        <div className="min-w-0">
          <h1 className="break-words text-xl font-semibold text-fg">{email.subject}</h1>
          <p className="truncate text-sm text-fg-muted">{email.sender}</p>
          <p className="text-xs text-fg-faint">
            {email.account_email} · {formatReceivedLong(email.received_at)}
          </p>
        </div>
      </div>

      <WhySortedBanner
        bucketLabel={meta.label}
        reasons={email.reasons}
        decisionSource={email.decision_source}
        confidence={email.confidence}
        needsReview={email.needs_review}
      />

      {email.summary_excerpt ? (
        <SafeMarkdown className="max-w-[var(--measure)] text-sm leading-6 text-fg">
          {email.summary_excerpt}
        </SafeMarkdown>
      ) : null}

      <div className="flex flex-col gap-2 rounded-[var(--radius-md)] border border-border bg-bg-muted p-3 text-sm text-fg-muted">
        <p>This is a preview — open in Gmail for the full message.</p>
        <OpenInGmailLink accountEmail={email.account_email} threadId={email.thread_id} />
      </div>

      <ReadingPaneActions
        email={email}
        onMarkRead={onMarkRead}
        markReadPending={markReadPending}
        hasNextMustRead={hasNextMustRead}
        onNextMustRead={onNextMustRead}
        online={online}
      />
    </Motion>
  );
}

/**
 * Derive up to two uppercase initials from a raw `From` value. Uses the
 * display name when present, otherwise the first letter of the address.
 *
 * @param sender - Raw sender string (display name and/or address).
 * @returns The initials for the avatar.
 */
function initialsFromSender(sender: string): string {
  const display = sender.includes('<') ? sender.split('<')[0].trim() : sender;
  const base = display || sender;
  const words = base.split(/\s+/).filter(Boolean);
  if (words.length >= 2 && words[0][0] && words[1][0]) {
    return (words[0][0] + words[1][0]).toUpperCase();
  }
  return (base[0] ?? '?').toUpperCase();
}
