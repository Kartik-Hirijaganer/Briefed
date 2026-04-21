import { forwardRef, type ButtonHTMLAttributes, type AnchorHTMLAttributes, type Ref } from 'react';

/**
 * Supported visual variants.
 */
export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'destructive' | 'link';

/**
 * Size token mapped to padding + font-size.
 */
export type ButtonSize = 'sm' | 'md' | 'lg';

interface BaseProps {
  /** Visual emphasis tier. */
  readonly variant: ButtonVariant;
  /** Sizing token. Defaults to `md`. */
  readonly size?: ButtonSize;
  /** Disable interactivity. */
  readonly disabled?: boolean;
  /** Show a spinner and prevent clicks while truthy. */
  readonly loading?: boolean;
}

interface ButtonAsButton extends BaseProps, ButtonHTMLAttributes<HTMLButtonElement> {
  readonly variant: Exclude<ButtonVariant, 'link'>;
  readonly href?: never;
}

interface ButtonAsLink extends BaseProps, AnchorHTMLAttributes<HTMLAnchorElement> {
  readonly variant: 'link';
  /** Destination URL — required whenever `variant === 'link'`. */
  readonly href: string;
}

/**
 * Discriminated-union props so invalid combinations are rejected at the
 * type level — e.g. `<Button variant="link" />` (no href) fails to compile.
 */
export type ButtonProps = ButtonAsButton | ButtonAsLink;

const VARIANT_CLASS: Record<ButtonVariant, string> = {
  primary: 'bg-accent text-accent-contrast hover:opacity-90',
  secondary: 'bg-surface text-fg border border-border hover:bg-border',
  ghost: 'bg-transparent text-fg hover:bg-surface',
  destructive: 'bg-danger text-accent-contrast hover:opacity-90',
  link: 'bg-transparent text-accent underline-offset-4 hover:underline',
};

const SIZE_CLASS: Record<ButtonSize, string> = {
  sm: 'h-8 px-3 text-xs rounded-[var(--radius-sm)]',
  md: 'h-10 px-4 text-sm rounded-[var(--radius-md)]',
  lg: 'h-12 px-6 text-base rounded-[var(--radius-md)] min-h-[44px]',
};

const BASE_CLASS =
  'inline-flex items-center justify-center gap-2 font-medium transition-opacity ' +
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)] ' +
  'focus-visible:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed';

/**
 * Accessible button primitive. Renders an `<a>` when `variant='link'` and a
 * `<button>` otherwise — the type system enforces that links receive `href`.
 *
 * @param props - Discriminated union of anchor-backed and button-backed props.
 * @param ref - Forwarded ref.
 * @returns The rendered element.
 */
export const Button = forwardRef<HTMLButtonElement | HTMLAnchorElement, ButtonProps>(
  function Button(props, ref): JSX.Element {
    const { variant, size = 'md', loading, className, children, ...rest } = props;
    const classes = [BASE_CLASS, VARIANT_CLASS[variant], SIZE_CLASS[size], className ?? '']
      .filter(Boolean)
      .join(' ');
    if (variant === 'link') {
      const { href, ...anchorRest } = rest as AnchorHTMLAttributes<HTMLAnchorElement> & {
        href: string;
      };
      return (
        <a
          {...anchorRest}
          href={href}
          ref={ref as Ref<HTMLAnchorElement>}
          className={classes}
          aria-busy={loading || undefined}
        >
          {children}
        </a>
      );
    }
    const buttonRest = rest as ButtonHTMLAttributes<HTMLButtonElement>;
    return (
      <button
        type={buttonRest.type ?? 'button'}
        {...buttonRest}
        ref={ref as Ref<HTMLButtonElement>}
        className={classes}
        aria-busy={loading || undefined}
        disabled={buttonRest.disabled || loading}
      >
        {children}
      </button>
    );
  },
);
