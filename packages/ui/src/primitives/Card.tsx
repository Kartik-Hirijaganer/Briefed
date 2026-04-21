import type { HTMLAttributes, ReactNode } from 'react';

/**
 * Props for {@link Card}.
 */
export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  /** Card body. */
  readonly children: ReactNode;
  /** When true, removes default padding so the caller owns spacing. */
  readonly flush?: boolean;
}

/**
 * Surface container used by every list row, settings panel, and dashboard
 * widget. Centralizes border + background + radius so feature code never
 * applies these tokens directly.
 *
 * @param props - Component props.
 * @returns The rendered surface.
 */
export function Card(props: CardProps): JSX.Element {
  const { children, flush, className, ...rest } = props;
  const padding = flush ? '' : 'p-4';
  const classes = [
    'rounded-[var(--radius-md)] border border-border bg-surface text-fg',
    padding,
    className ?? '',
  ]
    .filter(Boolean)
    .join(' ');
  return (
    <div {...rest} className={classes}>
      {children}
    </div>
  );
}
