import { Alert, Button, Card } from '@briefed/ui';
import { useState, type ChangeEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import { CONSENT_SUMMARY } from '../content/legal';
import { useAddGmailFlow } from '../hooks/useAddGmailFlow';

const APP_RETURN_TO_PATTERN = /^\/app(?:\/[^/].*)?$/;

const POLICY_LINK_CLASS =
  'text-link underline-offset-4 transition-[color,box-shadow,text-decoration-color] ' +
  'duration-[var(--motion-fast)] ease-[var(--ease-standard)] hover:underline ' +
  'focus-visible:outline-none focus-visible:ring-2 ' +
  'focus-visible:ring-[var(--focus-ring)] focus-visible:ring-offset-2';

const DEMO_LINK_CLASS =
  'inline-flex h-[var(--control-height)] items-center justify-center rounded-[var(--radius-md)] ' +
  'px-[var(--space-4)] text-[length:var(--fs-sm)] font-medium leading-[var(--lh-sm)] ' +
  'text-link underline-offset-4 transition-[color,box-shadow,text-decoration-color] ' +
  'duration-[var(--motion-fast)] ease-[var(--ease-standard)] hover:underline ' +
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] ' +
  'focus-visible:ring-offset-2';

/**
 * Returns a safe internal post-OAuth path.
 *
 * @param value - Candidate path from the login `next` parameter.
 * @returns A safe `/app` path.
 */
const sanitizeReturnTo = (value: string | null): string => {
  if (!value || value.includes('\\')) return '/app';
  return APP_RETURN_TO_PATTERN.test(value) ? value : '/app';
};

const AUTH_ERROR_MESSAGES: Record<string, string> = {
  access_denied: 'Google sign-in was cancelled or access was denied. Please try again.',
  invalid_request: "Google's sign-in response was incomplete. Please try again.",
  oauth_session_invalid:
    'Google sign-in lost its browser session. Please try again and allow cookies for this site.',
};

const describeAuthError = (code: string | null): string | null => {
  if (!code) return null;
  return AUTH_ERROR_MESSAGES[code] ?? 'Google sign-in did not complete. Please try again.';
};

/**
 * Reads the build-time Gmail-connect flag. Any value except literal `true`
 * keeps live OAuth disabled.
 *
 * @returns True when the live Gmail OAuth CTA should be enabled.
 */
const isGmailConnectEnabled = (): boolean => import.meta.env.VITE_ENABLE_GMAIL_CONNECT === 'true';

/**
 * Real Gmail login page with informed pre-consent. Delegates OAuth start
 * to the backend, so the frontend never touches Google tokens.
 *
 * @returns The rendered login card.
 */
export default function LoginPage(): JSX.Element {
  const [params] = useSearchParams();
  const [acceptedPreConsent, setAcceptedPreConsent] = useState<boolean>(false);
  const authError = describeAuthError(params.get('auth_error'));
  const gmailConnectEnabled = isGmailConnectEnabled();
  const addGmail = useAddGmailFlow({ returnTo: sanitizeReturnTo(params.get('next')) });
  const continueDisabled = !gmailConnectEnabled || !acceptedPreConsent;
  const continueLabel = gmailConnectEnabled
    ? 'Continue with Google'
    : 'Available soon — try the demo.';

  const handlePreConsentChange = (event: ChangeEvent<HTMLInputElement>): void => {
    setAcceptedPreConsent(event.target.checked);
  };

  const handleContinue = (): void => {
    if (continueDisabled) return;
    addGmail.start();
  };

  return (
    <main className="flex min-h-[100dvh] items-center justify-center bg-bg-canvas px-[var(--space-4)] py-[var(--space-8)] text-fg md:px-[var(--space-8)]">
      <Card className="w-full max-w-[var(--measure)]">
        <div className="flex flex-col gap-[var(--space-6)]">
          <div className="flex flex-col gap-[var(--space-2)]">
            <h1 className="font-display text-[length:var(--fs-2xl)] font-semibold leading-[var(--lh-2xl)] tracking-[var(--tracking-tight)] text-fg">
              Connect Gmail to Briefed
            </h1>
            <p className="text-[length:var(--fs-base)] leading-[var(--lh-base)] text-fg-muted">
              Connect Gmail only if you want Briefed to process your real mailbox for priority
              ranking, summaries, sender recommendations, and user-initiated mark-read actions.
            </p>
          </div>

          {authError ? (
            <Alert tone="danger" title="Sign-in failed">
              <p>{authError}</p>
            </Alert>
          ) : null}

          <section
            aria-labelledby="gmail-access-summary"
            className="flex flex-col gap-[var(--space-3)]"
          >
            <h2
              id="gmail-access-summary"
              className="font-display text-[length:var(--fs-lg)] font-semibold leading-[var(--lh-lg)] text-fg"
            >
              What you are agreeing to
            </h2>
            <ul className="flex list-disc flex-col gap-[var(--space-2)] pl-[var(--space-6)] text-[length:var(--fs-sm)] leading-[var(--lh-sm)] text-fg-muted">
              {CONSENT_SUMMARY.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </section>

          <Alert tone="warn" title="Not for HIPAA-regulated data">
            <p>
              Do not connect mailboxes used for protected health information or workflows that
              require a dedicated HIPAA compliance program.
            </p>
          </Alert>

          <Alert tone="warn" title="Google verification warning">
            <p>
              Google will show an unverified app warning while Briefed is pending verification.
              Choose Advanced, then proceed to continue.
            </p>
          </Alert>

          <p className="text-[length:var(--fs-sm)] leading-[var(--lh-sm)] text-fg-muted">
            Review the{' '}
            <a
              className={POLICY_LINK_CLASS}
              href="/privacy"
              target="_blank"
              rel="noopener noreferrer"
            >
              Privacy Policy
            </a>{' '}
            and{' '}
            <a
              className={POLICY_LINK_CLASS}
              href="/terms"
              target="_blank"
              rel="noopener noreferrer"
            >
              Terms
            </a>{' '}
            before continuing.
          </p>

          <label className="flex gap-[var(--space-3)] rounded-[var(--radius-md)] border border-border bg-bg-muted p-[var(--space-3)] text-[length:var(--fs-sm)] leading-[var(--lh-sm)] text-fg">
            <input
              type="checkbox"
              className="mt-[var(--space-1)] h-[var(--space-4)] w-[var(--space-4)] rounded-[var(--radius-sm)] border-border-strong accent-accent"
              checked={acceptedPreConsent}
              onChange={handlePreConsentChange}
            />
            <span>
              I understand Briefed will process my Gmail data under the Privacy Policy and Terms
            </span>
          </label>

          <Button
            variant="primary"
            size="lg"
            onClick={handleContinue}
            disabled={continueDisabled}
            aria-label={continueLabel}
          >
            {continueLabel}
          </Button>

          <Link to="/demo" className={DEMO_LINK_CLASS}>
            Try Demo instead
          </Link>
        </div>
      </Card>
    </main>
  );
}
