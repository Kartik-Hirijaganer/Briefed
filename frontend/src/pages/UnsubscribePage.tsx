import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { Badge, Button, Card, EmptyState, ErrorState, FreshnessBadge, Skeleton } from '@briefed/ui';

import { api, unwrap } from '../api/client';
import type { Schemas } from '../api/types';
import { useFreshnessState } from '../hooks/useFreshnessState';
import { useOnlineStatus } from '../hooks/useOnlineStatus';
import { enqueueMutation } from '../offline/mutations';

const STALE_MS = 10 * 60 * 1000;

/**
 * Unsubscribe recommendations (`/unsubscribe`). Release 1.0.0 never
 * clicks unsubscribe on the user's behalf per ADR 0006 — the user
 * confirms each suggestion; we record the dismissal only.
 *
 * @returns The rendered page.
 */
export default function UnsubscribePage(): JSX.Element {
  const client = useQueryClient();
  const online = useOnlineStatus();
  const suggestionsQuery = useQuery({
    queryKey: ['unsubscribes'],
    queryFn: async () => unwrap(await api.GET('/api/v1/unsubscribes')),
    staleTime: STALE_MS,
  });
  const freshness = useFreshnessState({ queryKey: ['unsubscribes'], staleTime: STALE_MS });

  const dismiss = useMutation({
    mutationFn: async (id: string): Promise<void> => {
      if (!online) {
        await enqueueMutation({ type: 'unsubscribe_dismiss', suggestionId: id });
        return;
      }
      unwrap(
        await api.POST('/api/v1/unsubscribes/{suggestion_id}/dismiss', {
          params: { path: { suggestion_id: id } },
        }),
      );
    },
    onMutate: (id) => removeSuggestionFromCache(client, id),
    onSuccess: () => {
      if (online) void client.invalidateQueries({ queryKey: ['unsubscribes'] });
    },
  });

  const confirm = useMutation({
    mutationFn: async (id: string): Promise<void> => {
      if (!online) {
        await enqueueMutation({ type: 'unsubscribe_confirm', suggestionId: id });
        return;
      }
      unwrap(
        await api.POST('/api/v1/unsubscribes/{suggestion_id}/confirm', {
          params: { path: { suggestion_id: id } },
        }),
      );
    },
    onMutate: (id) => removeSuggestionFromCache(client, id),
    onSuccess: () => {
      if (online) void client.invalidateQueries({ queryKey: ['unsubscribes'] });
    },
  });

  return (
    <section className="flex flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-xl font-semibold tracking-tight">Unsubscribe suggestions</h1>
          <FreshnessBadge
            state={freshness.state}
            lastKnownGoodAt={freshness.lastKnownGoodAt ?? undefined}
          />
        </div>
      </header>

      {suggestionsQuery.isPending ? (
        <Skeleton shape="block" />
      ) : suggestionsQuery.isError ? (
        <ErrorState
          title="Could not load suggestions"
          detail={
            suggestionsQuery.error instanceof Error ? suggestionsQuery.error.message : undefined
          }
        />
      ) : suggestionsQuery.data && suggestionsQuery.data.suggestions.length > 0 ? (
        <ul className="flex flex-col gap-3">
          {suggestionsQuery.data.suggestions.map((suggestion) => (
            <li key={suggestion.id}>
              <Card className="flex flex-col gap-2">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h3 className="truncate text-sm font-semibold text-fg">
                      {suggestion.sender_email}
                    </h3>
                    <p className="truncate text-xs text-fg-muted">{suggestion.sender_domain}</p>
                  </div>
                  <Badge tone="warn">score {Number(suggestion.confidence).toFixed(2)}</Badge>
                </div>
                <p className="text-xs text-fg-muted">{suggestion.rationale}</p>
                <div className="flex items-center gap-2">
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => dismiss.mutate(suggestion.id)}
                  >
                    Keep
                  </Button>
                  {unsubscribeUrl(suggestion) ? (
                    <Button variant="link" size="sm" href={unsubscribeUrl(suggestion) ?? '#'}>
                      Open unsubscribe link
                    </Button>
                  ) : null}
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={() => confirm.mutate(suggestion.id)}
                  >
                    Mark unsubscribed
                  </Button>
                </div>
              </Card>
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState
          icon="check"
          title="No suggestions right now"
          description="Run a scan — we only recommend when engagement drops below the configured threshold."
        />
      )}
    </section>
  );
}

function unsubscribeUrl(suggestion: Schemas['UnsubscribeSuggestion']): string | null {
  return suggestion.list_unsubscribe?.http_urls[0] ?? null;
}

function removeSuggestionFromCache(
  client: ReturnType<typeof useQueryClient>,
  suggestionId: string,
): void {
  client.setQueryData<Schemas['UnsubscribesListResponse']>(['unsubscribes'], (current) => {
    if (!current) return current;
    return {
      suggestions: current.suggestions.filter((suggestion) => suggestion.id !== suggestionId),
    };
  });
}
