import type { Schemas } from './types';

/**
 * Parameter object for the paginated email-list query.
 */
export interface EmailsQueryParams {
  /** Optional bucket filter. */
  readonly bucket?: Schemas['EmailRow']['bucket'];
  /** Pagination offset. */
  readonly offset: number;
  /** Page size. */
  readonly limit: number;
}

/**
 * Build the digest-today query key.
 *
 * @returns Query key for today's digest.
 */
export function digestToday(): readonly ['digest-today'] {
  return ['digest-today'];
}

/**
 * Build the email-list query key.
 *
 * @param params - Optional email-list filters and pagination values.
 * @returns Query key for either all email lists or one parameterized list.
 */
export function emails(
  params?: EmailsQueryParams,
): readonly ['emails'] | readonly ['emails', EmailsQueryParams] {
  return params ? ['emails', params] : ['emails'];
}

/**
 * Build the unsubscribe-suggestions query key.
 *
 * @returns Query key for unsubscribe suggestions.
 */
export function unsubscribes(): readonly ['unsubscribes'] {
  return ['unsubscribes'];
}

/**
 * Build the unsubscribe hygiene aggregate query key.
 *
 * @returns Query key for hygiene aggregates.
 */
export function hygiene(): readonly ['hygiene'] {
  return ['hygiene'];
}

/**
 * Build the client config query key.
 *
 * @returns Query key for client config.
 */
export function clientConfig(): readonly ['client-config'] {
  return ['client-config'];
}

/**
 * Build the run-history query key.
 *
 * @returns Query key for run history.
 */
export function history(): readonly ['history'] {
  return ['history'];
}

/**
 * Build the single-run query key.
 *
 * @param id - Run id, or an empty value while the route parameter is unresolved.
 * @returns Query key for one run.
 */
export function run(id: string | null | undefined): readonly ['run', string | null | undefined] {
  return ['run', id];
}

/**
 * Build the connected-accounts query key.
 *
 * @returns Query key for connected accounts.
 */
export function accounts(): readonly ['accounts'] {
  return ['accounts'];
}

/**
 * Build the preferences query key.
 *
 * @returns Query key for user preferences.
 */
export function preferences(): readonly ['preferences'] {
  return ['preferences'];
}

/**
 * Build the schedule query key.
 *
 * @returns Query key for the user's scan schedule.
 */
export function schedule(): readonly ['profile', 'schedule'] {
  return ['profile', 'schedule'];
}

/**
 * Build the rubric query key.
 *
 * @returns Query key for rubric rules.
 */
export function rubric(): readonly ['rubric'] {
  return ['rubric'];
}

/**
 * Build the legal-consent query key.
 *
 * @returns Query key for legal consent state.
 */
export function legalConsent(): readonly ['legal-consent'] {
  return ['legal-consent'];
}
