import { Button, Card } from '@briefed/ui';

import { useAddGmailFlow } from '../hooks/useAddGmailFlow';

/**
 * Unauthenticated landing page. Delegates OAuth start to the backend —
 * frontend never touches Google tokens (plan §11). Mirrors the iOS
 * standalone-PWA escape hatch (§19.16 §6) via `useAddGmailFlow`.
 *
 * @returns The rendered login card.
 */
export default function LoginPage(): JSX.Element {
  const addGmail = useAddGmailFlow({ returnTo: '/' });
  return (
    <main className="flex min-h-[100dvh] items-center justify-center bg-bg-muted px-6">
      <Card className="max-w-md">
        <div className="flex flex-col gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Welcome to Briefed</h1>
            <p className="mt-1 text-sm text-fg-muted">
              Sign in with Google to connect your first mailbox. We request read-only Gmail access
              and never send, archive, or click unsubscribe on your behalf.
            </p>
          </div>
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
