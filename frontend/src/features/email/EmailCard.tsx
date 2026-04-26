import { Card, Motion, OpenInGmailLink, WhyBadge } from '@briefed/ui';

import type { Schemas } from '../../api/types';

/**
 * Props for {@link EmailCard}.
 */
export interface EmailCardProps {
  /** Single classified email row. */
  readonly email: Schemas['EmailRow'];
  /** Optional swipe handler: right promotes, left ignores. */
  readonly onBucketChange?: (
    email: Schemas['EmailRow'],
    bucket: Schemas['EmailRow']['bucket'],
  ) => void;
}

const SWIPE_THRESHOLD_PX = 96;

/**
 * Base card used on every triage list + must-read preview. Satisfies the
 * plan §19.8 explainability lint rule (`<WhyBadge>` + `<OpenInGmailLink>`
 * both present on every row).
 *
 * @param props - Component props.
 * @returns The rendered row.
 */
export function EmailCard(props: EmailCardProps): JSX.Element {
  const { email, onBucketChange } = props;
  const received = new Date(email.received_at).toLocaleString();

  const move = (bucket: Schemas['EmailRow']['bucket']): void => {
    if (!onBucketChange || bucket === email.bucket) return;
    onBucketChange(email, bucket);
  };

  return (
    <div className="relative overflow-hidden rounded-[var(--radius-md)]">
      {onBucketChange ? (
        <div
          aria-hidden="true"
          className="absolute inset-0 flex items-center justify-between bg-surface px-4 text-xs font-medium"
        >
          <span className="text-accent">Must read</span>
          <span className="text-fg-muted">Ignore</span>
        </div>
      ) : null}
      <Motion
        drag={onBucketChange ? 'x' : false}
        dragConstraints={{ left: 0, right: 0 }}
        dragElastic={0.18}
        onDragEnd={(_event, info) => {
          if (info.offset.x >= SWIPE_THRESHOLD_PX) move('must_read');
          if (info.offset.x <= -SWIPE_THRESHOLD_PX) move('ignore');
        }}
      >
        <Card className="flex flex-col gap-2">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h3 className="truncate text-sm font-semibold text-fg">{email.subject}</h3>
              <p className="truncate text-xs text-fg-muted">
                {email.sender} · {email.account_email}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <WhyBadge
                reasons={email.reasons}
                decisionSource={email.decision_source}
                confidence={email.confidence}
              />
            </div>
          </div>
          {email.summary_excerpt ? (
            <p className="line-clamp-2 text-sm text-fg-muted">{email.summary_excerpt}</p>
          ) : null}
          <div className="flex items-center justify-between text-xs text-fg-muted">
            <time dateTime={email.received_at}>{received}</time>
            <OpenInGmailLink accountEmail={email.account_email} threadId={email.thread_id} />
          </div>
        </Card>
      </Motion>
      {onBucketChange ? (
        <div className="sr-only">
          <button type="button" onClick={() => move('must_read')}>
            Move to must read
          </button>
          <button type="button" onClick={() => move('ignore')}>
            Move to ignore
          </button>
        </div>
      ) : null}
    </div>
  );
}
