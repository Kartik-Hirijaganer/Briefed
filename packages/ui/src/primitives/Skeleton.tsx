/**
 * Props for {@link Skeleton}.
 */
export interface SkeletonProps {
  /** Shape token — determines width/height defaults. */
  readonly shape?: 'line' | 'block' | 'avatar' | 'pill';
  /** Optional explicit width (CSS length). */
  readonly width?: string;
  /** Optional explicit height (CSS length). */
  readonly height?: string;
  /** Extra classnames to layer on. */
  readonly className?: string;
}

const SHAPE_CLASS: Record<NonNullable<SkeletonProps['shape']>, string> = {
  line: 'h-4 w-full rounded-[var(--radius-sm)]',
  block: 'h-24 w-full rounded-[var(--radius-md)]',
  avatar: 'h-10 w-10 rounded-full',
  pill: 'h-6 w-16 rounded-full',
};

/**
 * Animated placeholder rendered while data loads. Consumers should crossfade
 * it out once real content arrives to avoid layout shift.
 *
 * @param props - Component props.
 * @returns The rendered shimmer block.
 */
export function Skeleton(props: SkeletonProps): JSX.Element {
  const { shape = 'line', width, height, className } = props;
  const style = { width, height };
  const classes = [
    'animate-pulse bg-border/70 motion-reduce:animate-none',
    SHAPE_CLASS[shape],
    className ?? '',
  ]
    .filter(Boolean)
    .join(' ');
  return <div aria-hidden="true" className={classes} style={style} />;
}
