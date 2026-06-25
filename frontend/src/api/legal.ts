import { api, unwrap } from './client';
import type { Schemas } from './types';

/**
 * Fetch the caller's legal-consent status.
 *
 * @returns Current policy versions and whether consent is required.
 * @throws ApiError when the request fails.
 */
export async function getLegalConsent(): Promise<Schemas['LegalConsentStatus']> {
  return unwrap(await api.GET('/api/v1/legal/consent'));
}

/**
 * Accept the current legal policy versions.
 *
 * @param payload - Privacy Policy and Terms versions the user reviewed.
 * @returns Updated legal-consent status.
 * @throws ApiError when the request fails or versions are stale.
 */
export async function acceptLegalConsent(
  payload: Schemas['LegalConsentRequest'],
): Promise<Schemas['LegalConsentStatus']> {
  return unwrap(
    await api.POST('/api/v1/legal/consent', {
      body: payload,
    }),
  );
}
