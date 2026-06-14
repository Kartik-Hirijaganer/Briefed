import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useRef, useState } from 'react';

import { getLegalConsent } from '../api/legal';
import { legalConsent } from '../api/queryKeys';
import type { Schemas } from '../api/types';
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
  const drainingRef = useRef<boolean>(false);
  const [draining, setDraining] = useState(false);
  const [lastReplayError, setLastReplayError] = useState<string | null>(null);
  const consent = useQuery<Schemas['LegalConsentStatus'], Error>({
    queryKey: legalConsent(),
    queryFn: getLegalConsent,
    enabled: false,
  });
  const consentRequired = consent.data?.consent_required === true;

  const drainNow = useCallback(async (): Promise<void> => {
    if (!online || drainingRef.current || consentRequired) return;
    drainingRef.current = true;
    setDraining(true);
    setLastReplayError(null);
    try {
      const result = await replayPendingMutations(queryClient);
      if (result.failed > 0) setLastReplayError('Some queued actions could not sync.');
    } catch (error) {
      setLastReplayError(error instanceof Error ? error.message : 'Queued action sync failed.');
    } finally {
      drainingRef.current = false;
      setDraining(false);
    }
  }, [consentRequired, online, queryClient]);

  useEffect(() => {
    if (!online || consentRequired) return;
    void drainNow();
  }, [consentRequired, drainNow, online]);

  return { draining, lastReplayError, drainNow };
}
