import { useQuery } from '@tanstack/react-query';

import { Card, EmptyState, ErrorState, Skeleton } from '@briefed/ui';

import { api, unwrap } from '../../api/client';

/**
 * Active rubric rules (`/settings/prompts`). Editing lands in a follow-up
 * phase; 1.0.0 only surfaces the rule list for inspection per plan §6.
 *
 * @returns The rendered page.
 */
export default function PromptsPage(): JSX.Element {
  const rubricQuery = useQuery({
    queryKey: ['rubric'],
    queryFn: async () => unwrap(await api.GET('/api/v1/rubric')),
  });

  if (rubricQuery.isPending) return <Skeleton shape="block" />;
  if (rubricQuery.isError) {
    return (
      <ErrorState
        title="Could not load rubric"
        detail={rubricQuery.error instanceof Error ? rubricQuery.error.message : undefined}
      />
    );
  }
  const data = rubricQuery.data;
  if (!data || data.rules.length === 0) {
    return (
      <EmptyState
        icon="bolt"
        title="No rubric rules defined yet"
        description="Add rules via the API or the seed config at packages/config/seeds."
      />
    );
  }

  return (
    <ul className="flex flex-col gap-3">
      {data.rules.map((rule) => (
        <li key={rule.id}>
          <Card className="flex flex-col gap-1">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-fg">{rule.label}</h3>
              <span className="text-xs text-fg-muted">
                priority {rule.priority} · {rule.bucket.replace('_', ' ')}
              </span>
            </div>
            <pre className="overflow-x-auto rounded-[var(--radius-sm)] bg-bg-muted p-2 text-xs text-fg-muted">
              {JSON.stringify(rule.predicate_json, null, 2)}
            </pre>
          </Card>
        </li>
      ))}
    </ul>
  );
}
