import type { CSSProperties, ReactNode } from 'react';

/**
 * Props for the {@link Motion} helper.
 */
export interface MotionProps {
  /** Children rendered inside the motion wrapper. */
  readonly children: ReactNode;
  /** Optional inline style overrides passed through to the wrapper element. */
  readonly style?: CSSProperties;
  /** Optional className so consumers can layer utility classes. */
  readonly className?: string;
}

/**
 * Placeholder motion wrapper — real framer-motion implementation lands in Phase 6.
 *
 * The primitive exists in Phase 0 so lint rules that forbid raw `motion.div`
 * outside `@briefed/ui` already have a valid import target. Until framer-motion
 * is wired in, Motion is a transparent `div`; transitions collapse to instant,
 * which matches the `prefers-reduced-motion: reduce` contract.
 *
 * @param props - Component props.
 * @returns A div wrapping `children`.
 */
export function Motion(props: MotionProps): JSX.Element {
  return (
    <div className={props.className} style={props.style}>
      {props.children}
    </div>
  );
}
