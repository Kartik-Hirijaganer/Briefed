import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';

import { replayPendingMutations } from '../offline/mutations';

import { useOnlineStatus } from './useOnlineStatus';

/**
 * Replays the durable offline mutation queue when connectivity returns.
 *
 * @returns Drain state for status UI.
 */
export function useSyncQueueDrain(): {
  draining: boolean;
  lastReplayError: string | null;
  drainNow: () => Promise<void>;
} {
  const online = useOnlineStatus();
  const queryClient = useQueryClient();
  const [draining, setDraining] = useState(false);
  const [lastReplayError, setLastReplayError] = useState<string | null>(null);

  const drainNow = async (): Promise<void> => {
    if (!online || draining) return;
    setDraining(true);
    setLastReplayError(null);
    try {
      const result = await replayPendingMutations(queryClient);
      if (result.failed > 0) setLastReplayError('Some queued actions could not sync.');
    } catch (error) {
      setLastReplayError(error instanceof Error ? error.message : 'Queued action sync failed.');
    } finally {
      setDraining(false);
    }
  };

  useEffect(() => {
    if (!online) return;
    void drainNow();
    // Drain when `online` flips true; `draining` intentionally stays outside
    // the dependency list so a state change does not start a second replay.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [online]);

  return { draining, lastReplayError, drainNow };
}

