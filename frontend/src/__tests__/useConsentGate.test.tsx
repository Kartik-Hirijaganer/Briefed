import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '../api/client';
import type { Schemas } from '../api/types';
import { useConsentGate } from '../hooks/useConsentGate';

const getLegalConsentMock = vi.hoisted(() => vi.fn());

vi.mock('../api/legal', () => ({
  getLegalConsent: getLegalConsentMock,
}));

const requiredConsent = (): Schemas['LegalConsentStatus'] => ({
  current_privacy_policy_version: 1,
  current_terms_version: 1,
  accepted_privacy_policy_version: 0,
  accepted_terms_version: 0,
  consent_required: true,
  accepted_at: null,
});

const acceptedConsent = (): Schemas['LegalConsentStatus'] => ({
  current_privacy_policy_version: 1,
  current_terms_version: 1,
  accepted_privacy_policy_version: 1,
  accepted_terms_version: 1,
  consent_required: false,
  accepted_at: '2026-06-14T00:00:00Z',
});

const wrap =
  (client: QueryClient) =>
  ({ children }: { readonly children: ReactNode }): JSX.Element => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );

const queryClient = (): QueryClient =>
  new QueryClient({ defaultOptions: { queries: { retry: false } } });

describe('useConsentGate', () => {
  const originalLocation = window.location;

  beforeEach(() => {
    getLegalConsentMock.mockReset();
  });

  afterEach(() => {
    Object.defineProperty(window, 'location', {
      value: originalLocation,
      configurable: true,
    });
    vi.restoreAllMocks();
  });

  it('returns required when the server reports stale consent', async () => {
    getLegalConsentMock.mockResolvedValue(requiredConsent());
    const { result } = renderHook(() => useConsentGate(), {
      wrapper: wrap(queryClient()),
    });

    await waitFor(() => expect(result.current.status).toBe('required'));
    expect(result.current).toMatchObject({ status: 'required', consent: requiredConsent() });
  });

  it('returns ok when the server reports current consent', async () => {
    getLegalConsentMock.mockResolvedValue(acceptedConsent());
    const { result } = renderHook(() => useConsentGate(), {
      wrapper: wrap(queryClient()),
    });

    await waitFor(() => expect(result.current.status).toBe('ok'));
    expect(result.current).toMatchObject({ status: 'ok', consent: acceptedConsent() });
  });

  it('redirects 401 responses to login with app child path preserved', async () => {
    const assign = vi.fn();
    Object.defineProperty(window, 'location', {
      value: {
        ...window.location,
        pathname: '/app/history',
        search: '?page=2',
        hash: '#run',
        assign,
      },
      configurable: true,
    });
    getLegalConsentMock.mockRejectedValue(new ApiError('unauthorized', 401, {}));

    const { result } = renderHook(() => useConsentGate(), {
      wrapper: wrap(queryClient()),
    });

    await waitFor(() => expect(assign).toHaveBeenCalled());
    expect(result.current.status).toBe('loading');
    expect(assign).toHaveBeenCalledWith('/login?next=%2Fapp%2Fhistory%3Fpage%3D2%23run');
  });

  it('surfaces non-auth errors for retry UI', async () => {
    getLegalConsentMock.mockRejectedValue(new ApiError('failed', 500, {}));
    const { result } = renderHook(() => useConsentGate(), {
      wrapper: wrap(queryClient()),
    });

    await waitFor(() => expect(result.current.status).toBe('error'));
    expect(result.current).toMatchObject({ status: 'error' });
  });
});
