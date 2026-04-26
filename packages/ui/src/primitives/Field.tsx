import {
  cloneElement,
  isValidElement,
  useId,
  type ReactElement,
  type ReactNode,
  type InputHTMLAttributes,
} from 'react';

/**
 * Props for {@link Field}.
 */
export interface FieldProps {
  /** Visible label text. */
  readonly label: string;
  /** Optional descriptive helper text rendered below the control. */
  readonly description?: string;
  /** Optional error message. When set, `aria-invalid` is applied. */
  readonly error?: string;
  /** Mark the field as required in the label. */
  readonly required?: boolean;
  /**
   * A single form control element — the primitive wires `id`,
   * `aria-describedby`, and `aria-invalid` into its props automatically.
   */
  readonly children: ReactElement<InputHTMLAttributes<HTMLElement>>;
}

/**
 * Accessible form-field wrapper — owns `<label htmlFor>`, description,
 * and error wiring so downstream inputs never re-implement a11y plumbing.
 *
 * @param props - Component props.
 * @returns The labelled field block.
 */
export function Field(props: FieldProps): JSX.Element {
  const { label, description, error, required, children } = props;
  const controlId = useId();
  const descriptionId = description ? `${controlId}-desc` : undefined;
  const errorId = error ? `${controlId}-err` : undefined;
  const describedBy = [descriptionId, errorId].filter(Boolean).join(' ') || undefined;

  const control: ReactNode = isValidElement(children)
    ? cloneElement(children, {
        id: controlId,
        'aria-describedby': describedBy,
        'aria-invalid': error ? true : undefined,
        'aria-required': required || undefined,
      })
    : children;

  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={controlId} className="text-sm font-medium text-fg">
        {label}
        {required ? <span className="ml-0.5 text-danger">*</span> : null}
      </label>
      {control}
      {description ? (
        <p id={descriptionId} className="text-xs text-fg-muted">
          {description}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} role="alert" className="text-xs text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}
