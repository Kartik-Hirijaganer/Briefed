/**
 * Props for {@link OpenInGmailLink}.
 */
export interface OpenInGmailLinkProps {
  /** Gmail account address — routed to the correct profile via `authuser`. */
  readonly accountEmail: string;
  /** Gmail-assigned thread id. */
  readonly threadId: string;
  /** Optional override label. Defaults to "Open in Gmail". */
  readonly label?: string;
}

/**
 * Builds the deep-link URL spec'd in plan §19.8 and renders it as an
 * external link. Every email row must surface this primitive so the user
 * can jump back to Gmail in one click.
 *
 * @param props - Component props.
 * @returns The rendered anchor.
 */
export function OpenInGmailLink(props: OpenInGmailLinkProps): JSX.Element {
  const { accountEmail, threadId, label = 'Open in Gmail' } = props;
  const encodedEmail = encodeURIComponent(accountEmail);
  const href = `https://mail.google.com/mail/?authuser=${encodedEmail}#inbox/${threadId}`;
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-xs text-accent underline-offset-4 hover:underline"
    >
      {label}
    </a>
  );
}
