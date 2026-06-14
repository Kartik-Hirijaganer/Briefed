import {
  Alert,
  Button,
  Dialog,
  EmptyState,
  ErrorState,
  FreshnessBadge,
  Motion,
  MOTION_PRESETS,
} from '@briefed/ui';
import { CircleCheck } from 'lucide-react';
import { useState } from 'react';

import { LIST_STAGGER_SECONDS } from '../config/presentation';
import { useDemoMode } from '../demo/DemoModeProvider';
import { SenderCard } from '../features/unsubscribe/SenderCard';
import { SenderCardSkeleton } from '../features/unsubscribe/SenderCardSkeleton';
import { UnsubscribeSelectionBar } from '../features/unsubscribe/UnsubscribeSelectionBar';
import { useUnsubscribeData } from '../features/unsubscribe/useUnsubscribeData';

/**
 * Unsubscribe suggestions (`/app/unsubscribe`). Multi-select sender triage with a
 * **capability-driven** bulk action: with the execute capability off (the prod
 * default) it is recommend-only — it opens each sender's unsubscribe link and
 * marks it handled. With the capability on (ADR 0014) the primary opens a
 * confirmation dialog and posts real one-click unsubscribes, surfacing
 * per-result follow-ups for senders that need a manual step or that failed.
 *
 * @returns The rendered page.
 */
export default function UnsubscribePage(): JSX.Element {
  const { isDemo } = useDemoMode();
  const data = useUnsubscribeData();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [executeDialogBusy, setExecuteDialogBusy] = useState(false);
  // Only the destructive execute path (capability on) is online-only (§5);
  // the recommend-only path stays usable offline (links best-effort, the
  // mark-handled /confirm enqueues for replay).
  const offlineExecuteBlocked = data.executeEnabled && !data.online;
  const primaryTooltip = isDemo
    ? 'Disabled in demo'
    : offlineExecuteBlocked
      ? 'Reconnect to unsubscribe'
      : undefined;

  const onPrimary = (): void => {
    if (data.executeEnabled) {
      setConfirmOpen(true);
      return;
    }
    data.recommendUnsubscribeSelected();
  };

  const onConfirmExecute = (): void => {
    setExecuteDialogBusy(true);
    void data.executeSelected().finally(() => {
      setExecuteDialogBusy(false);
      setConfirmOpen(false);
    });
  };

  return (
    <section className="flex flex-col gap-4">
      <header className="flex flex-col gap-1">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="font-display text-xl font-semibold tracking-tight">
            Unsubscribe suggestions
          </h1>
          <FreshnessBadge
            state={data.freshnessState}
            lastKnownGoodAt={data.freshnessLastKnownGoodAt ?? undefined}
          />
        </div>
        <p className="text-sm text-fg-muted">
          {data.flaggedCount} senders flagged · ~{data.wastedPerMonth} wasted emails / month
        </p>
      </header>

      {data.batchSummary ? (
        <Alert
          tone="info"
          title="Unsubscribe results"
          action={
            <Button variant="ghost" size="sm" onClick={data.dismissBatchSummary}>
              Dismiss
            </Button>
          }
        >
          <p>
            {data.batchSummary.unsubscribed} unsubscribed · {data.batchSummary.manualRequired} need
            a manual step · {data.batchSummary.failed} failed
          </p>
          <ManualLinkList data={data} />
        </Alert>
      ) : null}

      {data.isPending ? (
        <SenderCardSkeleton />
      ) : data.isError ? (
        <ErrorState
          title="Could not load suggestions"
          detail={data.error instanceof Error ? data.error.message : undefined}
        />
      ) : data.suggestions.length > 0 ? (
        <>
          <UnsubscribeSelectionBar
            total={data.totalCount}
            selectedCount={data.selectedCount}
            allSelected={data.allSelected}
            indeterminate={data.someSelected && !data.allSelected}
            onToggleAll={data.togglePageSelected}
            onKeep={data.keepSelected}
            keepDisabled={isDemo || data.selectedCount === 0}
            onPrimary={onPrimary}
            primaryLabel={`Unsubscribe ${data.selectedCount} selected`}
            primaryDisabled={isDemo || data.selectedCount === 0 || offlineExecuteBlocked}
            primaryLoading={data.primaryBusy}
            primaryTooltip={primaryTooltip}
            disabled={isDemo}
          />
          <ul className="flex flex-col gap-3">
            {data.suggestions.map((suggestion, index) => (
              <li key={suggestion.id}>
                <Motion
                  pace="base"
                  {...MOTION_PRESETS.listItem}
                  transition={{ delay: index * LIST_STAGGER_SECONDS }}
                >
                  <SenderCard
                    suggestion={suggestion}
                    selected={data.selectedIds.has(suggestion.id)}
                    onToggle={(checked) => data.toggleSelected(suggestion.id, checked)}
                    executeResult={data.executeResults.get(suggestion.id) ?? null}
                    onConfirmManual={() => data.confirmManual(suggestion.id)}
                    onRetry={() => void data.retryExecute(suggestion.id)}
                    disabled={isDemo}
                  />
                </Motion>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <EmptyState
          icon={CircleCheck}
          title="No suggestions right now"
          description="Run a scan — we only recommend when engagement drops below the configured threshold."
        />
      )}

      <Dialog
        open={confirmOpen}
        onClose={() => {
          if (!executeDialogBusy) setConfirmOpen(false);
        }}
        title={`Unsubscribe from ${data.selectedCount} senders?`}
        description="Briefed sends one-click requests where supported; others open for you to finish."
        footer={
          <>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setConfirmOpen(false)}
              disabled={executeDialogBusy}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              size="sm"
              onClick={onConfirmExecute}
              loading={executeDialogBusy}
            >
              Unsubscribe
            </Button>
          </>
        }
      >
        <p className="text-sm text-fg-muted">
          This sends a one-click unsubscribe to each sender that supports it. Senders that need a
          manual step will stay listed with a link to finish.
        </p>
      </Dialog>
    </section>
  );
}

/**
 * The explicit list of manual-step links from the most recent execute batch
 * (no auto-opened tabs — the user clicks each).
 *
 * @param props - Component props.
 * @param props.data - The unsubscribe data bundle.
 * @returns The rendered manual-link list, or null when there are none.
 */
function ManualLinkList(props: {
  data: ReturnType<typeof useUnsubscribeData>;
}): JSX.Element | null {
  const { data } = props;
  const manual = data.suggestions.filter((suggestion) => {
    const entry = data.executeResults.get(suggestion.id);
    return entry?.status === 'manual_required' && entry.manualUrl;
  });
  if (manual.length === 0) return null;
  return (
    <ul className="mt-2 flex flex-col gap-1">
      {manual.map((suggestion) => {
        const url = data.executeResults.get(suggestion.id)?.manualUrl;
        return (
          <li key={suggestion.id} className="text-xs">
            <span className="text-fg-muted">{suggestion.sender_email}: </span>
            <a
              href={url ?? '#'}
              target="_blank"
              rel="noopener noreferrer"
              className="text-link underline-offset-4 hover:underline"
            >
              Open unsubscribe page
            </a>
          </li>
        );
      })}
    </ul>
  );
}
