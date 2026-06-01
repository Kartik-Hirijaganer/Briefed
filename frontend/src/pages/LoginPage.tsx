import { Alert, Button, Card } from '@briefed/ui';
import { useSearchParams } from 'react-router-dom';

import { useAddGmailFlow } from '../hooks/useAddGmailFlow';

const sanitizeReturnTo = (value: string | null): string => {
  if (!value || !value.startsWith('/') || value.startsWith('//')) return '/';
  return value;
};

const AUTH_ERROR_MESSAGES: Record<string, string> = {
  access_denied: 'Google sign-in was cancelled or access was denied. Please try again.',
  invalid_request: "Google's sign-in response was incomplete. Please try again.",
};

const describeAuthError = (code: string | null): string | null => {
  if (!code) return null;
  return AUTH_ERROR_MESSAGES[code] ?? 'Google sign-in did not complete. Please try again.';
};

/**
 * Unauthenticated landing page. Delegates OAuth start to the backend —
 * frontend never touches Google tokens (plan §11). Mirrors the iOS
 * standalone-PWA escape hatch (§19.16 §6) via `useAddGmailFlow`.
 *
 * @returns The rendered login card.
 */
export default function LoginPage(): JSX.Element {
  const [params] = useSearchParams();
  const authError = describeAuthError(params.get('auth_error'));
  const addGmail = useAddGmailFlow({ returnTo: sanitizeReturnTo(params.get('next')) });
  return (
    <main className="flex min-h-[100dvh] items-center justify-center bg-bg-muted px-6">
      <Card className="max-w-md">
        <div className="flex flex-col gap-4">
          <div>
            <h1 className="font-display text-2xl font-semibold tracking-tight">
              Welcome to Briefed
            </h1>
            <p className="mt-1 text-sm text-fg-muted">
              Sign in with Google to connect your first mailbox. We request read-only Gmail access
              and never send, archive, or click unsubscribe on your behalf.
            </p>
          </div>
          {authError ? (
            <Alert tone="danger" title="Sign-in failed">
              <p>{authError}</p>
            </Alert>
          ) : null}
          <Button variant="primary" onClick={addGmail.start} aria-label="Continue with Google">
            Continue with Google
          </Button>
          <p className="text-xs text-fg-muted">
            By continuing you accept that your Gmail metadata is processed by the self-hosted
            Briefed instance you connect to. See the README security section for details.
          </p>
        </div>
      </Card>
    </main>
  );
}
