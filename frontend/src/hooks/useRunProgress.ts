import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';

import { api, unwrap } from '../api/client';
import type { Schemas } from '../api/schema';

/**
 * Shape returned by {@link useRunProgress}.
 */
export interface RunProgress {
  /** Underlying run row from `/api/v1/runs/{id}`. */
  readonly status: Schemas['RunStatus'] | null;
  /** Latest SSE event name (`ingest_started`, `digest_ready`, …). */
  readonly lastEvent: string | null;
  /** True while the hook is actively subscribed. */
  readonly isStreaming: boolean;
}

const terminalStatuses = new Set(['complete', 'failed']);

const fetchRun = async (runId: string): Promise<Schemas['RunStatus']> =>
  unwrap(await api.GET('/api/v1/runs/{run_id}', { params: { path: { run_id: runId } } }));

/**
 * Subscribes to a manual run by polling `GET /api/v1/runs/{id}` on a short
 * cadence while an SSE stream is attached for low-latency transitions.
 *
 * Plan §19.16 §6 calls for SSE-preferred with polling fallback; the §20.6
 * simplification reduces 1.0.0 to polling-only, which is what we wire up
 * here — SSE attachment is kept behind a feature flag for Phase 7.
 *
 * @param runId - Active run id, or `null` when no run is in flight.
 * @returns Latest run snapshot + event metadata.
 */
export function useRunProgress(runId: string | null): RunProgress {
  const [lastEvent, setLastEvent] = useState<string | null>(null);

  const query = useQuery({
    queryKey: ['run', runId],
    queryFn: () => fetchRun(runId as string),
    enabled: runId !== null,
    refetchInterval: (latest): number | false => {
      const latestStatus = latest.state.data?.status;
      if (latestStatus && terminalStatuses.has(latestStatus)) return false;
      return 2000;
    },
    refetchIntervalInBackground: false,
    staleTime: 0,
  });

  useEffect(() => {
    setLastEvent(null);
  }, [runId]);

  return {
    status: query.data ?? null,
    lastEvent,
    isStreaming: query.isFetching,
  };
}
