import { useQuery } from '@tanstack/react-query';

import { Button, EmptyState, ErrorState, Skeleton } from '@briefed/ui';

import { api, unwrap } from '../../api/client';
import { AppVersion } from '../../components/AppVersion';
import { AccountCard } from '../../features/settings/AccountCard';
import { ProfileSettings } from '../../features/settings/ProfileSettings';
import { useAddGmailFlow } from '../../hooks/useAddGmailFlow';
import { useBreakpoint } from '../../hooks/useBreakpoint';

/**
 * Settings landing page (plan §19.16 §1 + Track C — Phase II.6).
 *
 * Lists connected Gmail mailboxes plus the Profile / Schedule /
 * Appearance / Privacy panels backed by the Track C profile API.
 *
 * @returns The rendered page.
 */
export default function AccountsPage(): JSX.Element {
  const accountsQuery = useQuery({
    queryKey: ['accounts'],
    queryFn: async () => unwrap(await api.GET('/api/v1/accounts')),
  });
  const breakpoint = useBreakpoint();
  const isMobile = breakpoint === 'sm';
  const addGmail = useAddGmailFlow({ link: true, returnTo: '/settings/accounts' });

  return (
    <section className="flex flex-col gap-6 pb-24 md:pb-0">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Gmail accounts</h2>
          <p className="text-sm text-fg-muted">
            Connect as many Gmail inboxes as you want. Each is scanned independently.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <AppVersion />
          {!isMobile ? (
            <Button
              variant="primary"
              size="md"
              onClick={addGmail.start}
              aria-label="Add Gmail account"
            >
              + Add Gmail
            </Button>
          ) : null}
        </div>
      </header>

      {accountsQuery.isPending ? (
        <div className="flex flex-col gap-3">
          <Skeleton shape="block" />
          <Skeleton shape="block" />
        </div>
      ) : accountsQuery.isError ? (
        <ErrorState
          title="Could not load accounts"
          detail={
            accountsQuery.error instanceof Error ? accountsQuery.error.message : undefined
          }
        />
      ) : accountsQuery.data && accountsQuery.data.accounts.length > 0 ? (
        <ul className="flex flex-col gap-3">
          {accountsQuery.data.accounts.map((account) => (
            <li key={account.id}>
              <AccountCard account={account} />
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState
          icon="mail"
          title="No Gmail accounts yet"
          description="Connect your first inbox. Briefed requests read-only Gmail access and never sends, archives, or unsubscribes on your behalf."
          cta={
            <Button variant="primary" onClick={addGmail.start} aria-label="Add Gmail account">
              Add Gmail
            </Button>
          }
        />
      )}

      <ProfileSettings />

      {isMobile ? (
        <div
          className="fixed inset-x-0 bottom-[76px] z-20 border-t border-border bg-bg/95 px-4 py-3 backdrop-blur md:hidden"
          style={{ paddingBottom: `calc(env(safe-area-inset-bottom) + 12px)` }}
        >
          <Button
            variant="primary"
            size="lg"
            onClick={addGmail.start}
            aria-label="Add Gmail account"
            className="w-full"
          >
            + Add Gmail
          </Button>
        </div>
      ) : null}
    </section>
  );
}
