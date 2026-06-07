/**
 * Presentational constants for the dashboard / reader surfaces.
 *
 * Everything here is display-only: labels, ordering, skeleton counts, and the
 * list-stagger timing. No business logic and — critically — no backend
 * coupling. These values are passed into `@briefed/ui` primitives as props;
 * the UI package must never import this module (it stays feature-agnostic).
 */

import type { BadgeTone, DecisionSource } from '@briefed/ui';

import type { Schemas } from '../api/types';

/** Triage bucket discriminant, mirrored from the generated email schema. */
export type Bucket = Schemas['EmailRow']['bucket'];

/** Display metadata for a triage bucket. */
export interface BucketMeta {
  /** Human-readable label. */
  readonly label: string;
  /** Badge tone token. */
  readonly tone: BadgeTone;
}

/**
 * Per-bucket label + tone. Moved verbatim from the old `DashboardPage` so it
 * is the single source of truth for bucket presentation across the reader,
 * filter tabs, and category pills.
 */
export const BUCKET_META: Readonly<Record<Bucket, BucketMeta>> = Object.freeze({
  must_read: { label: 'Must-Read', tone: 'accent' },
  good_to_read: { label: 'Good-to-Read', tone: 'success' },
  ignore: { label: 'Ignore', tone: 'neutral' },
});

/** Stable bucket ordering for tabs and any bucket iteration. */
export const BUCKET_ORDER: readonly Bucket[] = Object.freeze([
  'must_read',
  'good_to_read',
  'ignore',
]);

/** A single filter-tab descriptor; `bucket: null` is the "All" tab. */
export interface FilterTab {
  /** Pill label. */
  readonly label: string;
  /** Bucket the pill selects, or `null` for the unfiltered view. */
  readonly bucket: Bucket | null;
}

/**
 * The four reader filter pills (All + one per bucket). Labels reuse
 * {@link BUCKET_META} so bucket naming stays consistent.
 */
export const FILTER_TABS: readonly FilterTab[] = Object.freeze([
  { label: 'All', bucket: null },
  { label: BUCKET_META.must_read.label, bucket: 'must_read' },
  { label: BUCKET_META.good_to_read.label, bucket: 'good_to_read' },
  { label: BUCKET_META.ignore.label, bucket: 'ignore' },
]);

/**
 * Reading-pane "why is this here" lead, keyed by decision source. Drives the
 * "Sorted by your rules" line in the reader header.
 */
export const SORTED_BY_LABEL: Readonly<Record<DecisionSource, string>> = Object.freeze({
  rule: 'Sorted by your rules',
  llm: 'Sorted by AI summary',
  hybrid: 'Sorted by your rules + AI',
});

/** Compact decision-source label (e.g. for chips / metadata lines). */
export const DECISION_SOURCE_LABEL: Readonly<Record<DecisionSource, string>> = Object.freeze({
  rule: 'Rule',
  llm: 'LLM',
  hybrid: 'Rule + LLM',
});

/**
 * Sort labels shown above the list. **Display-only** — the `/emails`
 * endpoint has no `sort` query param, so this is a static caption and must
 * not be wired to a request.
 */
export const SORT_OPTIONS = Object.freeze(['Newest'] as const);

/** Per-item entrance delay (seconds) for staggered list animations. */
export const LIST_STAGGER_SECONDS = 0.03;

/** Skeleton placeholder counts per surface. */
export const SKELETON_COUNTS = Object.freeze({
  emails: 6,
  senders: 4,
});

/**
 * Static helper caption. There is **no** keyboard-navigation infrastructure;
 * this is honest copy only — do not build keyboard handling around it.
 */
export const KEYBOARD_HINT = 'Select a message to read it here.';

/**
 * Format an ISO timestamp as an absolute, human-readable long date/time for
 * the reading pane (e.g. "May 31, 2026, 2:00 PM").
 *
 * @param iso - ISO-8601 timestamp.
 * @returns The localized absolute date/time string.
 */
export function formatReceivedLong(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

/**
 * Format an ISO timestamp as a compact relative age for list rows (e.g.
 * "just now", "5 min", "3 h", "2 d").
 *
 * @param iso - ISO-8601 timestamp.
 * @returns The compact relative-age string.
 */
export function formatReceivedRelative(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  if (diffMs < 60_000) return 'just now';
  const minutes = Math.round(diffMs / 60_000);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h`;
  const days = Math.round(hours / 24);
  return `${days} d`;
}
