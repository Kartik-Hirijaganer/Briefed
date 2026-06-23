import type { CSSProperties } from 'react';
import { useId } from 'react';

/**
 * Props for the standalone Briefed ranked-bar mark.
 */
export interface BriefedMarkProps {
  /** Rendered width and height in CSS pixels. */
  readonly size?: number;
  /** Optional class names for color and layout overrides. */
  readonly className?: string;
  /** Accessible title; omit when the mark is decorative. */
  readonly title?: string;
}

/**
 * Props for the Briefed horizontal wordmark.
 */
export interface BriefedWordmarkProps {
  /** Rendered mark size in CSS pixels. */
  readonly size?: number;
}

type WordmarkStyle = CSSProperties & {
  '--briefed-wordmark-size': string;
};

/**
 * Renders the ranked-bar Briefed mark.
 *
 * @param props - Component props.
 * @param props.size - Rendered width and height in CSS pixels.
 * @param props.className - Optional class names for color and layout overrides.
 * @param props.title - Accessible title; omit when the mark is decorative.
 * @returns The SVG mark.
 */
export function BriefedMark({ size = 32, className = '', title }: BriefedMarkProps): JSX.Element {
  const titleId = useId();

  return (
    <svg
      viewBox="0 0 100 100"
      width={size}
      height={size}
      role={title ? 'img' : undefined}
      aria-labelledby={title ? titleId : undefined}
      aria-hidden={title ? undefined : true}
      focusable="false"
      className={className}
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      {title ? <title id={titleId}>{title}</title> : null}
      <rect x="23" y="25" width="54" height="11" rx="5.5" fill="currentColor" />
      <rect x="23" y="43" width="42" height="11" rx="5.5" fill="currentColor" opacity="0.78" />
      <rect x="23" y="61" width="30" height="11" rx="5.5" fill="currentColor" opacity="0.54" />
      <rect x="23" y="79" width="18" height="11" rx="5.5" fill="currentColor" opacity="0.32" />
    </svg>
  );
}

/**
 * Renders the Briefed mark next to the product wordmark.
 *
 * @param props - Component props.
 * @param props.size - Rendered mark size in CSS pixels.
 * @returns The inline wordmark.
 */
export function BriefedWordmark({ size = 32 }: BriefedWordmarkProps): JSX.Element {
  const style: WordmarkStyle = {
    '--briefed-wordmark-size': `${size}px`,
  };

  return (
    <span
      aria-label="Briefed"
      className="inline-flex items-center gap-[var(--space-2)] text-accent"
      style={style}
    >
      <BriefedMark size={size} />
      <span className="font-display text-[calc(var(--briefed-wordmark-size)*0.75)] font-semibold leading-none tracking-[var(--tracking-tighter)] text-fg">
        Briefed
      </span>
    </span>
  );
}
