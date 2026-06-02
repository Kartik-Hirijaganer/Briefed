import type { LucideIcon } from 'lucide-react';
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
  /** Optional lucide icon component, rendered monochrome beside the title. */
  readonly icon?: LucideIcon | undefined;
}

/**
 * Centralized error block used by every list-style view that can fail.
 *
 * @param props - Component props.
 * @returns The rendered error block.
 */
export function ErrorState(props: ErrorStateProps): JSX.Element {
  const { title, detail, action, icon: Icon } = props;
  return (
    <div
      role="alert"
      className="flex flex-col gap-3 rounded-[var(--radius-md)] border border-danger/40 bg-danger/5 p-4 text-sm text-danger"
    >
      <strong className={`text-base${Icon ? ' flex items-center gap-2' : ''}`}>
        {Icon ? <Icon aria-hidden="true" strokeWidth={1.75} className="h-4 w-4 shrink-0" /> : null}
        {title}
      </strong>
      {detail ? <p className="text-fg-muted">{detail}</p> : null}
      {action}
    </div>
  );
}
