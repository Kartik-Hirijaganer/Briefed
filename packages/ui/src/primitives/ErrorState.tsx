import type { ReactNode } from 'react';

/**
 * Props for {@link ErrorState}.
 */
export interface ErrorStateProps {
  /** Heading copy — typically the failure class. */
  readonly title: string;
  /** Details from the thrown error (already user-safe). */
  readonly detail?: string | undefined;
  /** Optional retry / recovery action. */
  readonly action?: ReactNode | undefined;
}

/**
 * Centralized error block used by every list-style view that can fail.
 *
 * @param props - Component props.
 * @returns The rendered error block.
 */
export function ErrorState(props: ErrorStateProps): JSX.Element {
  const { title, detail, action } = props;
  return (
    <div
      role="alert"
      className="flex flex-col gap-3 rounded-[var(--radius-md)] border border-danger/40 bg-danger/5 p-4 text-sm text-danger"
    >
      <strong className="text-base">{title}</strong>
      {detail ? <p className="text-danger/80">{detail}</p> : null}
      {action}
    </div>
  );
}
