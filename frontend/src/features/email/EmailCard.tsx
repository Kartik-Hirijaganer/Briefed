import { Card, OpenInGmailLink, WhyBadge } from '@briefed/ui';

import type { Schemas } from '../../api/schema';

/**
 * Props for {@link EmailCard}.
 */
export interface EmailCardProps {
  /** Single classified email row. */
  readonly email: Schemas['EmailRow'];
}

/**
 * Base card used on every triage list + must-read preview. Satisfies the
 * plan §19.8 explainability lint rule (`<WhyBadge>` + `<OpenInGmailLink>`
 * both present on every row).
 *
 * @param props - Component props.
 * @returns The rendered row.
 */
export function EmailCard(props: EmailCardProps): JSX.Element {
  const { email } = props;
  const received = new Date(email.received_at).toLocaleString();
  return (
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
  );
}
