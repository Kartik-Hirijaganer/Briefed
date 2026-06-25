import { useQuery, type RefetchOptions, type QueryObserverResult } from '@tanstack/react-query';
import { useEffect } from 'react';

import { ApiError } from '../api/client';
import { getLegalConsent } from '../api/legal';
import { legalConsent } from '../api/queryKeys';
import type { Schemas } from '../api/types';

const LOGIN_PATH = '/login';
const APP_CHILD_PATH_PATTERN = /^\/app\/[^/]/;

/**
 * Loading state for the authenticated legal-consent gate.
 */
export interface ConsentGateLoadingState {
  /** Discriminant for shell rendering. */
  readonly status: 'loading';
}

/**
 * State returned when the caller must accept current legal policies.
 */
export interface ConsentGateRequiredState {
  /** Discriminant for shell rendering. */
  readonly status: 'required';
  /** Server-reported consent status. */
  readonly consent: Schemas['LegalConsentStatus'];
}

/**
 * State returned when the caller has already accepted current policies.
 */
export interface ConsentGateOkState {
  /** Discriminant for shell rendering. */
  readonly status: 'ok';
  /** Server-reported consent status. */
  readonly consent: Schemas['LegalConsentStatus'];
}

/**
 * State returned when consent status cannot be loaded.
 */
export interface ConsentGateErrorState {
  /** Discriminant for shell rendering. */
  readonly status: 'error';
  /** Query error from the consent-status request. */
  readonly error: Error;
  /** Retry the consent-status request. */
  readonly retry: (
    options?: RefetchOptions,
  ) => Promise<QueryObserverResult<Schemas['LegalConsentStatus'], Error>>;
}

/**
 * Discriminated union of legal-consent states for authenticated app routes.
 */
export type ConsentGateState =
  | ConsentGateLoadingState
  | ConsentGateRequiredState
  | ConsentGateOkState
  | ConsentGateErrorState;

/**
 * Load current legal-consent status for authenticated app routes.
 *
 * @returns Gate state used by AppShell to hard-branch before child routes mount.
 */
export function useConsentGate(): ConsentGateState {
  const query = useQuery<Schemas['LegalConsentStatus'], Error>({
    queryKey: legalConsent(),
    queryFn: getLegalConsent,
    staleTime: 0,
    gcTime: 0,
    retry: false,
  });

  useEffect(() => {
    if (!(query.error instanceof ApiError) || query.error.status !== 401) return;
    window.location.assign(buildConsentLoginRedirectPath());
  }, [query.error]);

  if (query.isPending || !query.isFetchedAfterMount) return { status: 'loading' };
  if (query.isError && query.error instanceof ApiError && query.error.status === 401) {
    return { status: 'loading' };
  }
  if (query.isError) return { status: 'error', error: query.error, retry: query.refetch };
  if (query.data.consent_required) return { status: 'required', consent: query.data };
  return { status: 'ok', consent: query.data };
}

const buildConsentLoginRedirectPath = (): string => {
  const pathname = window.location.pathname;
  if (!APP_CHILD_PATH_PATTERN.test(pathname)) return LOGIN_PATH;
  const currentPath = `${pathname}${window.location.search}${window.location.hash}`;
  const params = new URLSearchParams({ next: currentPath });
  return `${LOGIN_PATH}?${params.toString()}`;
};
