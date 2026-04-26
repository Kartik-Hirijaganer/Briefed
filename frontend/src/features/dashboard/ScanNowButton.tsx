import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { Button, Motion } from '@briefed/ui';

import { api, unwrap } from '../../api/client';
import type { Schemas } from '../../api/types';
import { useBreakpoint } from '../../hooks/useBreakpoint';
import { useOnlineStatus } from '../../hooks/useOnlineStatus';
import { useRunProgress } from '../../hooks/useRunProgress';

/** Browser event used by dashboard pull-to-refresh to trigger Scan Now. */
export const SCAN_NOW_EVENT = 'briefed-scan-now';

const SUCCESS_RESET_MS = 4000;

type ScanMode = 'idle' | 'running' | 'success' | 'error';

/**
 * Trigger surface for `POST /api/v1/runs`. Renders as a desktop button
 * (sticky action row top-right of the dashboard) and a full-width pinned
 * card on mobile that expands during the running state to show per-account
 * progress (plan §19.16 §3 + §6 + §20.5 polling).
 *
 * @returns The rendered control.
 */
export function ScanNowButton(): JSX.Element {
  const online = useOnlineStatus();
  const breakpoint = useBreakpoint();
  const isMobile = breakpoint === 'sm';
  const client = useQueryClient();
  const navigate = useNavigate();
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [justFinishedCount, setJustFinishedCount] = useState<number | null>(null);

  const accountsQuery = useQuery({
    queryKey: ['accounts'],
    queryFn: async () => unwrap(await api.GET('/api/v1/accounts')),
    staleTime: 60 * 1000,
  });
  const accountsCount = accountsQuery.data?.accounts.length ?? 0;
  const lastSyncIso = accountsQuery.data?.accounts.reduce<string | null>((acc, a) => {
    if (!a.last_sync_at) return acc;
    if (!acc) return a.last_sync_at;
    return new Date(a.last_sync_at) > new Date(acc) ? a.last_sync_at : acc;
  }, null);

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [online, activeRunId, startRun.isPending]);

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
    const timer = window.setTimeout(() => setJustFinishedCount(null), SUCCESS_RESET_MS);
    return () => window.clearTimeout(timer);
  }, [justFinishedCount]);

  const mode: ScanMode = ((): ScanMode => {
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
        return isMobile
          ? `✓ ${justFinishedCount ?? 0} new emails · tap to view`
          : `✓ Scanned ${justFinishedCount ?? 0} new emails`;
      case 'error':
        return '⚠ Retry';
      default:
        return '🔄 Scan now';
    }
  })();

  const tooltip = !online ? 'Connect to the internet to scan.' : undefined;
  const handleSuccessTap = (): void => {
    if (mode === 'success') navigate('/must-read');
  };

  if (isMobile) {
    return (
      <Motion
        layout
        pace="base"
        className="flex flex-col gap-2 rounded-[var(--radius-md)] border border-border bg-accent/5 p-3 shadow-[var(--shadow-1)]"
        onClick={handleSuccessTap}
      >
        <Button
          variant="primary"
          size="lg"
          onClick={triggerScan}
          disabled={!online || mode === 'running'}
          loading={mode === 'running'}
          title={tooltip}
          aria-label="Start a manual scan"
          className="w-full"
        >
          {label}
        </Button>
        {mode === 'running' ? (
          <ul className="flex flex-col gap-1 text-xs text-fg-muted">
            {(accountsQuery.data?.accounts ?? []).map((account) => (
              <li key={account.id} className="flex items-center justify-between gap-2">
                <span className="truncate">{account.email}</span>
                <span className="shrink-0">{progress.status?.stats?.ingested ?? 0} ingested</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-fg-muted">
            {accountsCount} {accountsCount === 1 ? 'account' : 'accounts'}
            {lastSyncIso ? ` · last scan ${formatRelative(lastSyncIso)}` : ''}
          </p>
        )}
        {mode === 'error' && startRun.error instanceof Error ? (
          <p role="alert" className="text-xs text-danger">
            {startRun.error.message}
          </p>
        ) : null}
      </Motion>
    );
  }

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

function formatRelative(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  if (diffMs < 60_000) return 'just now';
  const minutes = Math.round(diffMs / 60_000);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return `${days} d ago`;
}
