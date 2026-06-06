import { Loader2 } from 'lucide-react';

/**
 * Props for {@link Spinner}.
 */
export interface SpinnerProps {
  /** Icon size token. `sm` = 16px, `md` = 20px. Defaults to `md`. */
  readonly size?: 'sm' | 'md';
  /**
   * Screen-reader label announced via an `sr-only` span inside the
   * `role="status"` wrapper. Omit when the spinner sits inside an element
   * that already conveys busy state (e.g. a `<Button loading>` with its own
   * `aria-busy`) so the spinner does not pollute that element's
   * accessible name.
   */
  readonly label?: string;
  /** Extra classnames layered on the wrapper. */
  readonly className?: string;
}

const SIZE_CLASS: Record<NonNullable<SpinnerProps['size']>, string> = {
  sm: 'h-4 w-4',
  md: 'h-5 w-5',
};

/**
 * The single processing-feedback primitive. Renders a spinning Lucide
 * `Loader2` that inherits `currentColor`, paused under
 * `prefers-reduced-motion`. The icon is `aria-hidden`; the `role="status"`
 * wrapper carries an optional `sr-only` label so screen readers announce the
 * busy state. Use this everywhere a "working…" indicator is needed — never a
 * scattered `animate-spin` block.
 *
 * @param props - Component props.
 * @returns The rendered status spinner.
 */
export function Spinner(props: SpinnerProps): JSX.Element {
  const { size = 'md', label, className } = props;
  const wrapperClasses = ['inline-flex items-center', className ?? ''].filter(Boolean).join(' ');
  return (
    <span role="status" className={wrapperClasses}>
      <Loader2
        aria-hidden="true"
        strokeWidth={1.75}
        className={`${SIZE_CLASS[size]} animate-spin motion-reduce:animate-none`}
      />
      <span className="sr-only">{label}</span>
    </span>
  );
}
