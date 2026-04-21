import { motion, useReducedMotion, type HTMLMotionProps, type Transition } from 'framer-motion';
import { forwardRef, type ReactNode, type Ref } from 'react';

/**
 * Props for the {@link Motion} helper.
 */
export interface MotionProps extends Omit<HTMLMotionProps<'div'>, 'children'> {
  /** Children rendered inside the motion wrapper. */
  readonly children: ReactNode;
  /**
   * Transition preset tier keyed to the three motion tokens
   * (`--motion-fast`, `--motion-base`, `--motion-slow`). Defaults to `base`.
   */
  readonly pace?: 'fast' | 'base' | 'slow';
}

const DURATIONS: Record<NonNullable<MotionProps['pace']>, number> = {
  fast: 0.12,
  base: 0.2,
  slow: 0.4,
};

/**
 * Central wrapper for all animated primitives. Enforces the three motion
 * tokens and collapses to instant transitions when the user prefers
 * reduced motion — features must compose this instead of raw `motion.div`.
 *
 * @param props - Component props.
 * @param ref - Forwarded DOM ref.
 * @returns A framer-motion div that animates according to `pace`.
 */
export const Motion = forwardRef<HTMLDivElement, MotionProps>(function Motion(
  props,
  ref: Ref<HTMLDivElement>,
): JSX.Element {
  const { children, pace = 'base', transition, ...rest } = props;
  const reduced = useReducedMotion();
  const resolvedTransition: Transition = reduced
    ? { duration: 0 }
    : { duration: DURATIONS[pace], ease: [0.2, 0, 0, 1], ...transition };
  return (
    <motion.div ref={ref} {...rest} transition={resolvedTransition}>
      {children}
    </motion.div>
  );
});
