import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import LoginPage from '../pages/LoginPage';

const startMock = vi.hoisted(() => vi.fn());
const useAddGmailFlowMock = vi.hoisted(() =>
  vi.fn(() => ({
    start: startMock,
    startUrl: '/api/v1/oauth/gmail/start?return_to=%2Fapp',
    opensInNewTab: false,
  })),
);

vi.mock('../hooks/useAddGmailFlow', () => ({
  useAddGmailFlow: useAddGmailFlowMock,
}));

const renderPage = (initialEntries: readonly string[] = ['/login']): void => {
  render(
    <MemoryRouter initialEntries={[...initialEntries]}>
      <LoginPage />
    </MemoryRouter>,
  );
};

describe('<LoginPage>', () => {
  beforeEach(() => {
    startMock.mockClear();
    useAddGmailFlowMock.mockClear();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('renders Gmail consent details, policy links, and the demo fallback', () => {
    renderPage();

    expect(
      screen.getByRole('heading', { level: 1, name: /connect gmail to briefed/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/gmail\.readonly/i)).toBeInTheDocument();
    expect(
      screen.getByText(/gmail\.modify only for user-initiated mark-read/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/userinfo\.email, userinfo\.profile, and openid/i)).toBeInTheDocument();
    expect(screen.getByText(/OpenRouter to Google Gemini 2\.5 Flash/i)).toBeInTheDocument();
    expect(screen.getByText(/not for HIPAA-regulated healthcare data/i)).toBeInTheDocument();
    expect(screen.getByText(/unverified app warning/i)).toBeInTheDocument();
    expect(screen.getByText(/choose advanced/i)).toBeInTheDocument();
    const privacyLink = screen.getByRole('link', { name: /privacy policy/i });
    const termsLink = screen.getByRole('link', { name: /^terms$/i });

    expect(privacyLink).toHaveAttribute('href', '/privacy');
    expect(privacyLink).toHaveAttribute('target', '_blank');
    expect(termsLink).toHaveAttribute('href', '/terms');
    expect(termsLink).toHaveAttribute('target', '_blank');
    expect(screen.getByRole('link', { name: /try demo instead/i })).toHaveAttribute(
      'href',
      '/demo',
    );
  });

  it('keeps live OAuth disabled by default even after pre-consent is checked', async () => {
    const user = userEvent.setup();
    renderPage();

    const connectButton = screen.getByRole('button', { name: /available soon/i });
    expect(connectButton).toBeDisabled();

    await user.click(
      screen.getByRole('checkbox', {
        name: /i understand briefed will process my gmail data/i,
      }),
    );

    expect(connectButton).toBeDisabled();
    expect(startMock).not.toHaveBeenCalled();
  });

  it('gates Google OAuth on the required checkbox when the flag is enabled', async () => {
    vi.stubEnv('VITE_ENABLE_GMAIL_CONNECT', 'true');
    const user = userEvent.setup();
    renderPage();

    const connectButton = screen.getByRole('button', { name: /continue with google/i });
    expect(connectButton).toBeDisabled();

    await user.click(
      screen.getByRole('checkbox', {
        name: /i understand briefed will process my gmail data/i,
      }),
    );
    expect(connectButton).toBeEnabled();

    await user.click(connectButton);
    expect(startMock).toHaveBeenCalledTimes(1);
  });

  it('uses the login next parameter as the OAuth return path', () => {
    renderPage(['/login?next=%2Fapp%2Fsettings%2Faccounts']);
    expect(useAddGmailFlowMock).toHaveBeenCalledWith({ returnTo: '/app/settings/accounts' });
  });

  it('falls back to the dashboard for unsafe next parameters', () => {
    renderPage(['/login?next=%2F%2Fevil.example']);
    expect(useAddGmailFlowMock).toHaveBeenCalledWith({ returnTo: '/app' });
  });

  it('surfaces a friendly error when the OAuth callback reports access_denied', () => {
    vi.stubEnv('VITE_ENABLE_GMAIL_CONNECT', 'true');

    renderPage(['/login?auth_error=access_denied']);

    expect(screen.getByText(/cancelled or access was denied/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /continue with google/i })).toBeInTheDocument();
  });

  it('surfaces retry guidance when the OAuth browser session is unavailable', () => {
    vi.stubEnv('VITE_ENABLE_GMAIL_CONNECT', 'true');

    renderPage(['/login?auth_error=oauth_session_invalid']);

    expect(screen.getByText(/lost its browser session/i)).toBeInTheDocument();
    expect(screen.getByText(/allow cookies for this site/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /continue with google/i })).toBeInTheDocument();
  });
});
