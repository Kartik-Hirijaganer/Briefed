import { useQuery } from '@tanstack/react-query';

import { Button, EmptyState, ErrorState, Skeleton } from '@briefed/ui';

import { api, unwrap } from '../../api/client';
import { AccountCard } from '../../features/settings/AccountCard';

/**
 * Connected-mailbox list + Add Gmail flow (plan §19.16 §1).
 *
 * @returns The rendered page.
 */
export default function AccountsPage(): JSX.Element {
  const accountsQuery = useQuery({
    queryKey: ['accounts'],
    queryFn: async () => unwrap(await api.GET('/api/v1/accounts')),
  });

  return (
    <section className="flex flex-col gap-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Gmail accounts</h2>
          <p className="text-sm text-fg-muted">
            Connect as many Gmail inboxes as you want. Each is scanned independently.
          </p>
        </div>
        <Button variant="link" href="/api/v1/oauth/gmail/start?link=true&return_to=/settings/accounts">
          + Add Gmail
        </Button>
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
            <Button variant="link" href="/api/v1/oauth/gmail/start?link=true&return_to=/settings/accounts">
              Add Gmail
            </Button>
          }
        />
      )}
    </section>
  );
}
