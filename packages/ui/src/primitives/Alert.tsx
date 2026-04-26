import type { ReactNode } from 'react';

/**
 * Semantic tone of the alert banner.
 */
export type AlertTone = 'info' | 'success' | 'warn' | 'danger';

/**
 * Props for {@link Alert}.
 */
export interface AlertProps {
  /** Alert tone — drives color tokens. */
  readonly tone: AlertTone;
  /** Heading copy. */
  readonly title: string;
  /** Optional body content. */
  readonly children?: ReactNode;
  /** Optional trailing action (e.g. dismiss button). */
  readonly action?: ReactNode;
}

const TONE_CLASS: Record<AlertTone, string> = {
  info: 'border-accent/40 bg-accent/5 text-accent',
  success: 'border-success/40 bg-success/5 text-success',
  warn: 'border-warn/40 bg-warn/5 text-warn',
  danger: 'border-danger/40 bg-danger/5 text-danger',
};

/**
 * Inline banner used for persistent contextual messaging (e.g. stale data
 * notice on the dashboard).
 *
 * @param props - Component props.
 * @returns The rendered banner.
 */
export function Alert(props: AlertProps): JSX.Element {
  const { tone, title, children, action } = props;
  const classes = [
    'flex items-start gap-3 rounded-[var(--radius-md)] border p-3 text-sm',
    TONE_CLASS[tone],
  ].join(' ');
  return (
    <div role="status" className={classes}>
      <div className="flex-1">
        <strong className="block font-medium">{title}</strong>
        {children ? <div className="mt-1">{children}</div> : null}
      </div>
      {action}
    </div>
  );
}
