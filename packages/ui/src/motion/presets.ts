import type { HTMLMotionProps } from 'framer-motion';

/**
 * An `initial`/`animate` pair spread directly onto a {@link Motion} element.
 * Presets carry opacity / translate only — {@link Motion}'s `pace` owns the
 * duration + easing (and the reduced-motion collapse), so a preset never
 * sets its own timing. The field types mirror framer-motion's own
 * `motion.div` prop types so a preset spreads onto `<Motion>` cleanly.
 */
export interface MotionPreset {
  /** Pre-animation state. */
  readonly initial: NonNullable<HTMLMotionProps<'div'>['initial']>;
  /** Settled state. */
  readonly animate: NonNullable<HTMLMotionProps<'div'>['animate']>;
}

/**
 * The frozen catalogue of motion entrance presets. Spread one onto a
 * `<Motion>` to animate consistently:
 *
 * ```tsx
 * <Motion pace="base" {...MOTION_PRESETS.fadeIn}>…</Motion>
 * ```
 *
 * List staggering is done at the call site by layering a per-item
 * `transition={{ delay: i * LIST_STAGGER_SECONDS }}` on top of `listItem` —
 * there is intentionally no `StaggerList` wrapper component.
 */
export const MOTION_PRESETS: Readonly<Record<'fadeIn' | 'fadeRise' | 'listItem', MotionPreset>> =
  Object.freeze({
    fadeIn: {
      initial: { opacity: 0 },
      animate: { opacity: 1 },
    },
    fadeRise: {
      initial: { opacity: 0, y: 8 },
      animate: { opacity: 1, y: 0 },
    },
    listItem: {
      initial: { opacity: 0, y: 6 },
      animate: { opacity: 1, y: 0 },
    },
  });
