import { useQuery } from '@tanstack/react-query';

import { Card, ErrorState, Skeleton } from '@briefed/ui';

import { api, unwrap } from '../../api/client';

/**
 * Schedule settings (`/settings/schedule`). Surfaces the user's configured
 * digest send hour and retention policy read-only — editing is a Phase 7
 * follow-up per plan §19.13.
 *
 * @returns The rendered page.
 */
export default function SchedulePage(): JSX.Element {
  const preferencesQuery = useQuery({
    queryKey: ['preferences'],
    queryFn: async () => unwrap(await api.GET('/api/v1/preferences')),
  });

  if (preferencesQuery.isPending) return <Skeleton shape="block" />;
  if (preferencesQuery.isError) {
    return (
      <ErrorState
        title="Could not load schedule"
        detail={
          preferencesQuery.error instanceof Error ? preferencesQuery.error.message : undefined
        }
      />
    );
  }
  const prefs = preferencesQuery.data;
  if (!prefs) return <Skeleton shape="block" />;

  return (
    <section className="flex flex-col gap-4">
      <Card>
        <h2 className="text-sm font-semibold text-fg">Daily digest</h2>
        <p className="mt-1 text-sm text-fg-muted">
          Sent at {String(prefs.digest_send_hour_utc).padStart(2, '0')}:00 UTC. Edit via{' '}
          <code className="rounded bg-bg-muted px-1 text-xs">PATCH /api/v1/preferences</code> (UI
          editor ships in 1.1).
        </p>
      </Card>
      <Card>
        <h2 className="text-sm font-semibold text-fg">Retention policy</h2>
        <pre className="mt-2 overflow-x-auto rounded-[var(--radius-sm)] bg-bg-muted p-2 text-xs text-fg-muted">
          {JSON.stringify(prefs.retention_policy_json, null, 2)}
        </pre>
      </Card>
    </section>
  );
}
