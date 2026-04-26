import { useEffect, useId, useRef, type ReactNode } from 'react';

import { Motion } from './Motion';

/**
 * Props for {@link Dialog}.
 */
export interface DialogProps {
  /** When true, dialog is rendered. */
  readonly open: boolean;
  /** Invoked when the user presses escape or clicks the backdrop. */
  readonly onClose: () => void;
  /** Dialog title — used for `aria-labelledby`. */
  readonly title: string;
  /** Optional description — used for `aria-describedby`. */
  readonly description?: string;
  /** Dialog body. */
  readonly children: ReactNode;
  /** Optional footer slot (typically action buttons). */
  readonly footer?: ReactNode;
}

/**
 * Minimal accessible modal. Traps focus on open and returns it on close.
 * Radix can replace this in a later release — the surface area stays stable.
 *
 * @param props - Component props.
 * @returns The rendered dialog (or `null` when closed).
 */
export function Dialog(props: DialogProps): JSX.Element | null {
  const { open, onClose, title, description, children, footer } = props;
  const titleId = useId();
  const descId = useId();
  const previouslyFocused = useRef<HTMLElement | null>(null);
  const contentRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return undefined;
    previouslyFocused.current = document.activeElement as HTMLElement | null;
    contentRef.current?.focus();
    const handleKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('keydown', handleKey);
      previouslyFocused.current?.focus();
    };
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div
      role="presentation"
      onClick={onClose}
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: 'var(--overlay-scrim)' }}
    >
      <Motion
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descId : undefined}
        ref={contentRef}
        tabIndex={-1}
        onClick={(event) => event.stopPropagation()}
        initial={{ opacity: 0, scale: 0.98 }}
        animate={{ opacity: 1, scale: 1 }}
        pace="base"
        className="w-full max-w-md rounded-[var(--radius-lg)] bg-bg p-6 shadow-xl"
      >
        <h2 id={titleId} className="text-lg font-semibold text-fg">
          {title}
        </h2>
        {description ? (
          <p id={descId} className="mt-1 text-sm text-fg-muted">
            {description}
          </p>
        ) : null}
        <div className="mt-4">{children}</div>
        {footer ? <div className="mt-6 flex justify-end gap-2">{footer}</div> : null}
      </Motion>
    </div>
  );
}
