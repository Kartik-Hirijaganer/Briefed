import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';

/**
 * Props for {@link EmptyState}.
 */
export interface EmptyStateProps {
  /** Optional lucide icon component, rendered monochrome (inherits `currentColor`). */
  readonly icon?: LucideIcon;
  /** Heading copy. */
  readonly title: string;
  /** Optional supporting paragraph. */
  readonly description?: string;
  /** Optional call-to-action node (typically a `<Button>`). */
  readonly cta?: ReactNode;
}

/**
 * Neutral empty-state block used when a list or data view has no content.
 *
 * @param props - Component props.
 * @returns The rendered placeholder block.
 */
export function EmptyState(props: EmptyStateProps): JSX.Element {
  const { icon: Icon, title, description, cta } = props;
  return (
    <div
      role="status"
      className="flex flex-col items-center gap-3 rounded-[var(--radius-md)] border border-dashed border-border bg-surface p-8 text-center"
    >
      {Icon ? (
        <Icon aria-hidden="true" strokeWidth={1.5} className="h-8 w-8 text-fg-faint" />
      ) : null}
      <h3 className="text-base font-semibold text-fg">{title}</h3>
      {description ? <p className="max-w-sm text-sm text-fg-muted">{description}</p> : null}
      {cta ? <div className="mt-2">{cta}</div> : null}
    </div>
  );
}
