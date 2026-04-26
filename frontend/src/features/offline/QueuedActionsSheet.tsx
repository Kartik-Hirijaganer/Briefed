import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { Badge, Button, Sheet } from '@briefed/ui';

import { useOnlineStatus } from '../../hooks/useOnlineStatus';
import { usePendingMutations } from '../../hooks/usePendingMutations';
import { removePendingMutation, replayPendingMutations } from '../../offline/mutations';
import type { PendingMutationRecord } from '../../offline/db';

const LABEL_BY_TYPE: Record<PendingMutationRecord['type'], string> = {
  account_patch: 'Account update',
  email_bucket_update: 'Email bucket change',
  preferences_patch: 'Preferences update',
  unsubscribe_confirm: 'Unsubscribe confirmation',
  unsubscribe_dismiss: 'Unsubscribe dismissal',
};

/**
 * User-visible queue inspector for offline actions.
 *
 * @returns Floating queue button plus bottom sheet.
 */
export function QueuedActionsSheet(): JSX.Element | null {
  const online = useOnlineStatus();
  const queryClient = useQueryClient();
  const { pendingMutations } = usePendingMutations();
  const [open, setOpen] = useState(false);
  const [syncing, setSyncing] = useState(false);

  if (pendingMutations.length === 0) return null;

  const syncNow = async (): Promise<void> => {
    if (!online || syncing) return;
    setSyncing(true);
    try {
      await replayPendingMutations(queryClient);
    } finally {
      setSyncing(false);
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="fixed bottom-[88px] right-4 z-40 flex min-h-[44px] items-center gap-2 rounded-[var(--radius-md)] border border-border bg-surface px-3 text-sm font-medium text-fg shadow-lg md:bottom-4"
      >
        <span aria-hidden="true">↻</span>
        <span>{pendingMutations.length} queued</span>
      </button>
      <Sheet open={open} onClose={() => setOpen(false)} title="Queued actions">
        <div className="flex flex-col gap-4">
          <div className="flex items-center justify-between gap-3">
            <Badge tone={online ? 'success' : 'warn'}>{online ? 'Online' : 'Offline'}</Badge>
            <Button
              variant="secondary"
              size="sm"
              disabled={!online}
              loading={syncing}
              onClick={() => void syncNow()}
            >
              Sync now
            </Button>
          </div>
          <ul className="flex max-h-[45svh] flex-col gap-3 overflow-y-auto pr-1">
            {pendingMutations.map((mutation) => (
              <li
                key={mutation.id}
                className="flex items-start justify-between gap-3 rounded-[var(--radius-md)] border border-border p-3"
              >
                <div className="min-w-0">
                  <p className="text-sm font-medium text-fg">{LABEL_BY_TYPE[mutation.type]}</p>
                  <p className="text-xs text-fg-muted">
                    {new Date(mutation.createdAt).toLocaleString()}
                    {mutation.attempts > 0 ? ` · ${mutation.attempts} attempts` : ''}
                  </p>
                  {mutation.lastError ? (
                    <p className="mt-1 text-xs text-danger">{mutation.lastError}</p>
                  ) : null}
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => void removePendingMutation(mutation.id)}
                >
                  Cancel
                </Button>
              </li>
            ))}
          </ul>
        </div>
      </Sheet>
    </>
  );
}
