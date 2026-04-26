import { useCallback, useEffect, useState } from 'react';

import { listPendingMutations, subscribeToPendingMutations } from '../offline/mutations';
import type { PendingMutationRecord } from '../offline/db';

/**
 * Reactive snapshot of the offline mutation queue.
 *
 * @returns Current queue rows plus an explicit refresh callback.
 */
export function usePendingMutations(): {
  pendingMutations: PendingMutationRecord[];
  refreshPendingMutations: () => Promise<void>;
} {
  const [pendingMutations, setPendingMutations] = useState<PendingMutationRecord[]>([]);

  const refreshPendingMutations = useCallback(async (): Promise<void> => {
    setPendingMutations(await listPendingMutations());
  }, []);

  useEffect(() => {
    void refreshPendingMutations();
    return subscribeToPendingMutations(() => {
      void refreshPendingMutations();
    });
  }, [refreshPendingMutations]);

  return { pendingMutations, refreshPendingMutations };
}
