import type { ReactNode } from 'react';

/**
 * Semantic tone for a {@link Badge}.
 */
export type BadgeTone = 'neutral' | 'accent' | 'success' | 'warn' | 'danger';

/**
 * Props for {@link Badge}.
 */
export interface BadgeProps {
  /** Tone for color tokens. Defaults to `neutral`. */
  readonly tone?: BadgeTone;
  /** Badge content. */
  readonly children: ReactNode;
  /** Optional aria-label — overrides visible text for screen readers. */
  readonly ariaLabel?: string;
}

const TONE_CLASS: Record<BadgeTone, string> = {
  neutral: 'bg-border text-fg',
  accent: 'bg-accent/10 text-accent',
  success: 'bg-success/10 text-success',
  warn: 'bg-warn/10 text-warn',
  danger: 'bg-danger/10 text-danger',
};

/**
 * Compact status pill used inline with text (counts, chips, tags).
 *
 * @param props - Component props.
 * @returns The rendered badge.
 */
export function Badge(props: BadgeProps): JSX.Element {
  const { tone = 'neutral', children, ariaLabel } = props;
  return (
    <span
      aria-label={ariaLabel}
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${TONE_CLASS[tone]}`}
    >
      {children}
    </span>
  );
}
