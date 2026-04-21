import { Alert, InstallPromptIOS } from '@briefed/ui';

import { useInstallPrompt } from '../../hooks/useInstallPrompt';
import { useOnlineStatus } from '../../hooks/useOnlineStatus';
import { usePendingMutations } from '../../hooks/usePendingMutations';
import { useStorageEstimate } from '../../hooks/useStorageEstimate';
import { useSyncQueueDrain } from '../../hooks/useSyncQueueDrain';

/**
 * Shell-level offline, queue, install, and storage-pressure banners.
 *
 * @returns Banner stack.
 */
export function OfflineBanners(): JSX.Element | null {
  const online = useOnlineStatus();
  const { pendingMutations } = usePendingMutations();
  const { lastReplayError } = useSyncQueueDrain();
  const storage = useStorageEstimate();
  const { showIOSInstallPrompt, dismissIOSInstallPrompt } = useInstallPrompt();

  const storagePressure =
    storage.usageRatio !== null && storage.usageRatio >= 0.8 ? storage.usageRatio : null;

  if (online && !lastReplayError && !storagePressure && !showIOSInstallPrompt) {
    return null;
  }

  return (
    <div className="mb-4 flex flex-col gap-3">
      {!online ? (
        <Alert tone="warn" title="Offline">
          <p>
            Showing saved data. {pendingMutations.length} queued action
            {pendingMutations.length === 1 ? '' : 's'} will sync when you reconnect.
          </p>
        </Alert>
      ) : null}
      {lastReplayError ? (
        <Alert tone="danger" title="Queued action sync failed">
          <p>{lastReplayError}</p>
        </Alert>
      ) : null}
      {storagePressure ? (
        <Alert tone="warn" title="Storage almost full">
          <p>
            Offline cache is using {Math.round(storagePressure * 100)}% of available browser
            storage. Older cached digests may be cleared by the browser.
          </p>
        </Alert>
      ) : null}
      {showIOSInstallPrompt ? (
        <InstallPromptIOS onDismiss={dismissIOSInstallPrompt} />
      ) : null}
    </div>
  );
}

