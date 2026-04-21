import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';

import { Button } from '@briefed/ui';

import { api, unwrap } from '../../api/client';
import type { Schemas } from '../../api/types';
import { useOnlineStatus } from '../../hooks/useOnlineStatus';
import { useRunProgress } from '../../hooks/useRunProgress';

/** Browser event used by dashboard pull-to-refresh to trigger Scan Now. */
export const SCAN_NOW_EVENT = 'briefed-scan-now';

/**
 * Starts a manual run (`POST /api/v1/runs`) and renders the four button
 * states (idle / running / success / error) described in plan §19.16 §3.
 * Offline-guard disables the button per §19.16 §6 since the user expects
 * immediate feedback on a trigger action.
 *
 * @returns The rendered button + inline progress line.
 */
export function ScanNowButton(): JSX.Element {
  const online = useOnlineStatus();
  const client = useQueryClient();
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [justFinishedCount, setJustFinishedCount] = useState<number | null>(null);

  const startRun = useMutation({
    mutationFn: async (): Promise<Schemas['ManualRunResponse']> =>
      unwrap(await api.POST('/api/v1/runs', { body: { kind: 'manual' } })),
    onSuccess: (data) => {
      setActiveRunId(data.run_id);
      setJustFinishedCount(null);
    },
  });

  const progress = useRunProgress(activeRunId);
  const triggerScan = (): void => {
    if (!online || activeRunId || startRun.isPending) return;
    startRun.mutate();
  };

  useEffect(() => {
    const handler = (): void => triggerScan();
    window.addEventListener(SCAN_NOW_EVENT, handler);
    return () => window.removeEventListener(SCAN_NOW_EVENT, handler);
  });

  useEffect(() => {
    if (!activeRunId) return;
    const status = progress.status?.status;
    if (status === 'complete') {
      setJustFinishedCount(progress.status?.stats?.new_must_read ?? 0);
      setActiveRunId(null);
      if ('vibrate' in navigator) navigator.vibrate(10);
      void client.invalidateQueries({ queryKey: ['digest-today'] });
      void client.invalidateQueries({ queryKey: ['emails'] });
    } else if (status === 'failed') {
      setActiveRunId(null);
    }
  }, [activeRunId, progress.status, client]);

  useEffect(() => {
    if (justFinishedCount === null) return undefined;
    const timer = window.setTimeout(() => setJustFinishedCount(null), 4000);
    return () => window.clearTimeout(timer);
  }, [justFinishedCount]);

  const mode = ((): 'idle' | 'running' | 'success' | 'error' => {
    if (activeRunId) return 'running';
    if (startRun.isError) return 'error';
    if (justFinishedCount !== null) return 'success';
    return 'idle';
  })();

  const label = ((): string => {
    switch (mode) {
      case 'running': {
        const done = progress.status?.stats?.ingested ?? 0;
        return `Scanning… ${done} emails`;
      }
      case 'success':
        return `✓ Scanned ${justFinishedCount ?? 0} new emails`;
      case 'error':
        return '⚠ Retry';
      default:
        return '🔄 Scan now';
    }
  })();

  const tooltip = !online ? 'Connect to the internet to scan.' : undefined;

  return (
    <div className="flex flex-col gap-2">
      <Button
        variant="primary"
        size="lg"
        onClick={triggerScan}
        disabled={!online || mode === 'running'}
        loading={mode === 'running'}
        title={tooltip}
        aria-label="Start a manual scan"
      >
        {label}
      </Button>
      {mode === 'error' && startRun.error instanceof Error ? (
        <p role="alert" className="text-xs text-danger">
          {startRun.error.message}
        </p>
      ) : null}
    </div>
  );
}
