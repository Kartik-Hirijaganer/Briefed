import { useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { Alert, Card } from '@briefed/ui';

/**
 * OAuth callback landing (`/oauth/callback`). Backend has already set the
 * session cookie by the time we arrive; we just display a status, invalidate
 * the accounts query so the new row shows up, and bounce to `next`.
 *
 * @returns The rendered status card.
 */
export default function OAuthCallbackPage(): JSX.Element {
  const [params] = useSearchParams();
  const status = params.get('status') ?? 'ok';
  const next = params.get('next') ?? '/settings/accounts';
  const error = params.get('error');
  const navigate = useNavigate();
  const client = useQueryClient();

  useEffect(() => {
    if (status === 'ok') {
      void client.invalidateQueries({ queryKey: ['accounts'] });
      const timer = window.setTimeout(() => navigate(next, { replace: true }), 800);
      return () => window.clearTimeout(timer);
    }
    return undefined;
  }, [status, next, navigate, client]);

  return (
    <main className="flex min-h-[100dvh] items-center justify-center bg-bg-muted px-6">
      <Card className="max-w-md">
        {status === 'ok' ? (
          <Alert tone="success" title="Account connected">
            <p>Redirecting to your settings…</p>
          </Alert>
        ) : (
          <Alert tone="danger" title="OAuth failed">
            <p>{error ?? 'Google did not complete the handshake. Try connecting again.'}</p>
          </Alert>
        )}
      </Card>
    </main>
  );
}
