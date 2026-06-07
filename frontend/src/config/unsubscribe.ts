/**
 * Presentational config for the unsubscribe page.
 *
 * **Important:** the thresholds here are *purely descriptive* — they pick the
 * chips/tags shown on a sender card. They are intentionally **distinct** from
 * the backend's authoritative recommend criteria (the aggregator flags a
 * sender on volume ≥ 5 / waste ≥ 50% / engagement ≤ 20%). Do not conflate the
 * two: the backend decides *whether a sender is recommended at all*; these
 * decide *how to label* a sender the backend already surfaced.
 */

import type { BadgeTone } from '@briefed/ui';

/** Descriptive sender tag keys, in fixed display order. */
export type SenderTag = 'noisy' | 'disengaged' | 'low_value';

/**
 * Thresholds for the descriptive sender chips (presentational only — see the
 * module header). Distinct from the backend's recommend criteria.
 */
export const UNSUBSCRIBE_TAG_CONFIG = Object.freeze({
  /** ``frequency_30d`` at/above this reads as "noisy". */
  noisyFreq30d: 20,
  /** ``engagement_score`` at/below this reads as "disengaged". */
  disengagedEngagement: 0.1,
  /** ``waste_rate`` at/above this reads as "low value". */
  lowValueWaste: 0.7,
});

/** Badge tone per descriptive tag. */
export const UNSUBSCRIBE_TAG_TONE: Readonly<Record<SenderTag, BadgeTone>> = Object.freeze({
  noisy: 'warn',
  disengaged: 'neutral',
  low_value: 'danger',
});

/** Display label per descriptive tag. */
export const UNSUBSCRIBE_TAG_LABEL: Readonly<Record<SenderTag, string>> = Object.freeze({
  noisy: 'Noisy',
  disengaged: 'Disengaged',
  low_value: 'Low value',
});

/** How many recent subject chips to show per card. */
export const RECENT_SUBJECTS_DISPLAY = 3;
