import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { legalConsent } from '../api/queryKeys';
import type { Schemas } from '../api/types';
import { PRIVACY_POLICY_VERSION, TERMS_VERSION } from '../content/legal';
import { ConsentGate } from '../features/consent/ConsentGate';

const acceptMock = vi.hoisted(() => vi.fn());
const logoutMock = vi.hoisted(() => vi.fn());

vi.mock('../api/legal', () => ({
  acceptLegalConsent: acceptMock,
}));
vi.mock('../api/session', () => ({
  logoutAndClearBrowserSession: logoutMock,
}));

const requiredConsent = (): Schemas['LegalConsentStatus'] => ({
  current_privacy_policy_version: PRIVACY_POLICY_VERSION,
  current_terms_version: TERMS_VERSION,
  accepted_privacy_policy_version: 0,
  accepted_terms_version: 0,
  consent_required: true,
  accepted_at: null,
});

const acceptedConsent = (): Schemas['LegalConsentStatus'] => ({
  current_privacy_policy_version: PRIVACY_POLICY_VERSION,
  current_terms_version: TERMS_VERSION,
  accepted_privacy_policy_version: PRIVACY_POLICY_VERSION,
  accepted_terms_version: TERMS_VERSION,
  consent_required: false,
  accepted_at: '2026-06-14T00:00:00Z',
});

const wrap =
  (client: QueryClient) =>
  ({ children }: { children: ReactNode }): JSX.Element => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );

describe('<ConsentGate>', () => {
  beforeEach(() => {
    acceptMock.mockReset();
    logoutMock.mockReset();
  });

  it('gates acceptance on the required checkbox and stores the returned status', async () => {
    const user = userEvent.setup();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const accepted = acceptedConsent();
    acceptMock.mockResolvedValue(accepted);

    render(<ConsentGate consent={requiredConsent()} />, { wrapper: wrap(client) });

    const acceptButton = screen.getByRole('button', { name: /^accept$/i });
    expect(acceptButton).toBeDisabled();

    await user.click(screen.getByRole('checkbox', { name: /i have read and agree/i }));
    await user.click(acceptButton);

    await waitFor(() => expect(acceptMock).toHaveBeenCalled());
    expect(acceptMock.mock.calls[0]?.[0]).toEqual({
      privacy_policy_version: PRIVACY_POLICY_VERSION,
      terms_version: TERMS_VERSION,
    });
    expect(client.getQueryData(legalConsent())).toEqual(accepted);
  });

  it('signs out when the user declines', async () => {
    const user = userEvent.setup();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    logoutMock.mockResolvedValue(undefined);

    render(<ConsentGate consent={requiredConsent()} />, { wrapper: wrap(client) });

    await user.click(screen.getByRole('button', { name: /decline & sign out/i }));

    await waitFor(() => expect(logoutMock).toHaveBeenCalled());
  });

  it('keeps the blocking dialog open on Escape', async () => {
    const user = userEvent.setup();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(<ConsentGate consent={requiredConsent()} />, { wrapper: wrap(client) });
    await user.keyboard('{Escape}');

    expect(
      screen.getByRole('dialog', { name: /review briefed's gmail data terms/i }),
    ).toBeInTheDocument();
  });
});
