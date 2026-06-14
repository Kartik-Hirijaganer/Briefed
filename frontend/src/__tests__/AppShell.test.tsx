import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { ConsentGateState } from '../hooks/useConsentGate';
import { AppShell } from '../shell/AppShell';

const consentGateMock = vi.hoisted(
  () =>
    ({
      state: {
        status: 'ok',
        consent: {
          current_privacy_policy_version: 1,
          current_terms_version: 1,
          accepted_privacy_policy_version: 1,
          accepted_terms_version: 1,
          consent_required: false,
          accepted_at: '2026-06-14T00:00:00Z',
        },
      },
    }) as { state: ConsentGateState },
);

vi.mock('../features/offline/OfflineBanners', () => ({
  OfflineBanners: () => <div data-testid="offline-banners" />,
}));
vi.mock('../features/offline/QueuedActionsSheet', () => ({
  QueuedActionsSheet: () => <div data-testid="queued-actions" />,
}));
vi.mock('../components/AppVersion', () => ({
  AppVersion: () => <span data-testid="app-version">v</span>,
}));
vi.mock('../hooks/useConsentGate', () => ({
  useConsentGate: () => consentGateMock.state,
}));

const acceptedConsent = (): ConsentGateState => ({
  status: 'ok',
  consent: {
    current_privacy_policy_version: 1,
    current_terms_version: 1,
    accepted_privacy_policy_version: 1,
    accepted_terms_version: 1,
    consent_required: false,
    accepted_at: '2026-06-14T00:00:00Z',
  },
});

const requiredConsent = (): ConsentGateState => ({
  status: 'required',
  consent: {
    current_privacy_policy_version: 1,
    current_terms_version: 1,
    accepted_privacy_policy_version: 0,
    accepted_terms_version: 0,
    consent_required: true,
    accepted_at: null,
  },
});

const wrap = (initial: string): JSX.Element => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initial]}>
        <Routes>
          <Route path="/app" element={<AppShell />}>
            <Route index element={<div data-testid="page">home</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
};

describe('<AppShell>', () => {
  beforeEach(() => {
    consentGateMock.state = acceptedConsent();
  });

  it('renders sidebar, bottom tab bar, version, offline banners and outlet content', () => {
    render(wrap('/app'));
    // The sidebar brand is now an icon-rail "B" glyph link (accessible name "Briefed").
    expect(screen.getByRole('link', { name: /briefed/i })).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: /primary mobile/i })).toBeInTheDocument();
    expect(screen.getByTestId('offline-banners')).toBeInTheDocument();
    expect(screen.getByTestId('queued-actions')).toBeInTheDocument();
    expect(screen.getByTestId('app-version')).toBeInTheDocument();
    expect(screen.getByTestId('page')).toBeInTheDocument();
  });

  it('does not mount the outlet or replay UI while legal consent is required', () => {
    consentGateMock.state = requiredConsent();

    render(wrap('/app'));

    expect(
      screen.getByRole('dialog', { name: /review briefed's gmail data terms/i }),
    ).toBeInTheDocument();
    expect(screen.queryByTestId('page')).not.toBeInTheDocument();
    expect(screen.queryByTestId('offline-banners')).not.toBeInTheDocument();
    expect(screen.queryByTestId('queued-actions')).not.toBeInTheDocument();
  });
});
