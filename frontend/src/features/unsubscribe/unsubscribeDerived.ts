/**
 * Pure derivation helpers for the unsubscribe page.
 *
 * All numeric fields arrive as strings (Pydantic ``Decimal``) so every helper
 * coerces with ``Number(...)`` and guards with ``Number.isFinite`` before
 * arithmetic. Thresholds come from ``config/unsubscribe.ts`` (presentational —
 * not the backend's authoritative recommend criteria).
 */

import type { Schemas } from '../../api/types';
import { type SenderTag, UNSUBSCRIBE_TAG_CONFIG } from '../../config/unsubscribe';

type Suggestion = Schemas['UnsubscribeSuggestion'];

/**
 * Count of flagged senders. The source of truth is exactly what is shown —
 * the hygiene/stats endpoint is wired for freshness/future use but does not
 * gate this header count.
 *
 * @param suggestions - Currently displayed suggestions.
 * @returns The number of flagged senders.
 */
export function flaggedCount(suggestions: readonly Suggestion[]): number {
  return suggestions.length;
}

/**
 * Estimate the wasted emails per month across all flagged senders:
 * ``Σ frequency_30d × waste_rate``, rounded. Each term is dropped if it is not
 * finite (defensive against malformed data).
 *
 * @param suggestions - Currently displayed suggestions.
 * @returns The rounded wasted-emails-per-month estimate.
 */
export function wastedEmailsPerMonth(suggestions: readonly Suggestion[]): number {
  let total = 0;
  for (const suggestion of suggestions) {
    const term = Number(suggestion.frequency_30d) * Number(suggestion.waste_rate);
    if (Number.isFinite(term)) total += term;
  }
  return Math.round(total);
}

/**
 * The opened-rate percentage for one sender (``engagement_score × 100``).
 *
 * @param suggestion - One suggestion row.
 * @returns The rounded opened percentage (0 when not finite).
 */
export function openedPercent(suggestion: Suggestion): number {
  const pct = Number(suggestion.engagement_score) * 100;
  return Number.isFinite(pct) ? Math.round(pct) : 0;
}

/**
 * Descriptive tags for one sender, in fixed display order. Presentational only
 * (see ``config/unsubscribe.ts``).
 *
 * @param suggestion - One suggestion row.
 * @returns The applicable tags (``noisy`` / ``disengaged`` / ``low_value``).
 */
export function senderTags(suggestion: Suggestion): readonly SenderTag[] {
  const tags: SenderTag[] = [];
  if (Number(suggestion.frequency_30d) >= UNSUBSCRIBE_TAG_CONFIG.noisyFreq30d) {
    tags.push('noisy');
  }
  if (Number(suggestion.engagement_score) <= UNSUBSCRIBE_TAG_CONFIG.disengagedEngagement) {
    tags.push('disengaged');
  }
  if (Number(suggestion.waste_rate) >= UNSUBSCRIBE_TAG_CONFIG.lowValueWaste) {
    tags.push('low_value');
  }
  return tags;
}

/**
 * The best unsubscribe URL for a sender, mirroring the backend's
 * ``UnsubscribeAction.preferred_url`` (first HTTPS, then first HTTP, then
 * ``mailto:``). The DTO does not serialize ``preferred_url``, so the UI derives
 * it from the stored action.
 *
 * @param suggestion - One suggestion row.
 * @returns The preferred URL, or ``null`` when nothing is actionable.
 */
export function preferredUnsubscribeUrl(suggestion: Suggestion): string | null {
  const action = suggestion.list_unsubscribe;
  if (!action) return null;
  const https = action.http_urls.find((url) => url.toLowerCase().startsWith('https://'));
  if (https) return https;
  if (action.http_urls.length > 0) return action.http_urls[0];
  return action.mailto ?? null;
}
