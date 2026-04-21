import { useEffect, useId, type ReactNode } from 'react';

import { Motion } from './Motion';

/**
 * Props for {@link Sheet}.
 */
export interface SheetProps {
  /** When true the sheet is visible. */
  readonly open: boolean;
  /** Invoked when the user requests close. */
  readonly onClose: () => void;
  /** Heading copy. */
  readonly title: string;
  /** Sheet body. */
  readonly children: ReactNode;
}

/**
 * Mobile-first bottom sheet. Used for action menus on `<AccountCard>`
 * (plan §19.16 §6) so thumb reach is preserved.
 *
 * @param props - Component props.
 * @returns The rendered sheet (or `null` when closed).
 */
export function Sheet(props: SheetProps): JSX.Element | null {
  const { open, onClose, title, children } = props;
  const titleId = useId();

  useEffect(() => {
    if (!open) return undefined;
    const handleKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div
      role="presentation"
      onClick={onClose}
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/50"
      style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
    >
      <Motion
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(event) => event.stopPropagation()}
        initial={{ y: '100%' }}
        animate={{ y: 0 }}
        transition={{ type: 'spring', stiffness: 260, damping: 30 }}
        className="w-full max-w-md rounded-t-[var(--radius-lg)] bg-bg p-6 shadow-xl"
      >
        <h2 id={titleId} className="text-base font-semibold text-fg">
          {title}
        </h2>
        <div className="mt-4">{children}</div>
      </Motion>
    </div>
  );
}
