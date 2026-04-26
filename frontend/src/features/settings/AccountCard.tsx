import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import {
  Badge,
  Button,
  Card,
  Dialog,
  Motion,
  Sheet,
  Switch,
  type BadgeTone,
} from '@briefed/ui';

import { api, unwrap } from '../../api/client';
import type { Schemas } from '../../api/types';
import { useAddGmailFlow } from '../../hooks/useAddGmailFlow';
import { useBreakpoint } from '../../hooks/useBreakpoint';
import { useOnlineStatus } from '../../hooks/useOnlineStatus';
import { enqueueMutation } from '../../offline/mutations';

const SWIPE_REVEAL_PX = 160;
const SWIPE_TRIGGER_PX = 80;

/**
 * Props for {@link AccountCard}.
 */
export interface AccountCardProps {
  /** The connected-mailbox row to render. */
  readonly account: Schemas['ConnectedAccount'];
}

const STATUS_TONE: Record<Schemas['ConnectedAccount']['status'], BadgeTone> = {
  active: 'success',
  paused: 'neutral',
  needs_reauth: 'warn',
  error: 'danger',
};

const STATUS_LABEL: Record<Schemas['ConnectedAccount']['status'], string> = {
  active: 'Active',
  paused: 'Paused',
  needs_reauth: 'Needs reauth',
  error: 'Error',
};

/**
 * Per-account tile rendered on `/settings/accounts`. Owns the three
 * controls specified in plan §19.16 §1: auto-scan switch, scan-this-now
 * button, overflow menu (rename / exclude / reconnect / disconnect).
 *
 * @param props - Component props.
 * @returns The rendered card.
 */
export function AccountCard(props: AccountCardProps): JSX.Element {
  const { account } = props;
  const client = useQueryClient();
  const online = useOnlineStatus();
  const breakpoint = useBreakpoint();
  const isMobile = breakpoint === 'sm';
  const reconnect = useAddGmailFlow({ link: true, returnTo: '/settings/accounts' });
  const [sheetOpen, setSheetOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [swipeRevealed, setSwipeRevealed] = useState(false);

  const patch = useMutation({
    mutationFn: async (body: Schemas['AccountPatchRequest']) => {
      if (!online) {
        await enqueueMutation({ type: 'account_patch', accountId: account.id, body });
        return { ...account, ...body };
      }
      return unwrap(
        await api.PATCH('/api/v1/accounts/{account_id}', {
          params: { path: { account_id: account.id } },
          body,
        }),
      );
    },
    onMutate: (body) => {
      client.setQueryData<Schemas['AccountsListResponse']>(['accounts'], (current) => {
        if (!current) return current;
        return {
          accounts: current.accounts.map((row) =>
            row.id === account.id ? applyAccountPatch(row, body) : row,
          ),
        };
      });
    },
    onSuccess: () => {
      if (online) void client.invalidateQueries({ queryKey: ['accounts'] });
    },
  });

  const disconnect = useMutation({
    mutationFn: async (): Promise<void> => {
      unwrap(
        await api.DELETE('/api/v1/accounts/{account_id}', {
          params: { path: { account_id: account.id } },
        }),
      );
    },
    onSuccess: () => {
      setConfirmOpen(false);
      void client.invalidateQueries({ queryKey: ['accounts'] });
    },
  });

  const effectiveAutoScan = account.auto_scan_enabled ?? true;

  const cardBody = (
    <Card className="flex flex-col gap-3">
      <div className="flex items-start gap-3">
        <div
          aria-hidden="true"
          className="flex h-10 w-10 items-center justify-center rounded-full bg-accent/10 text-sm font-semibold uppercase text-accent"
        >
          {account.email.charAt(0)}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="truncate text-sm font-semibold text-fg">
              {account.display_name || account.email}
            </h3>
            <Badge tone={STATUS_TONE[account.status]}>{STATUS_LABEL[account.status]}</Badge>
          </div>
          <p className="truncate text-xs text-fg-muted">{account.email}</p>
          <p className="mt-1 text-xs text-fg-muted">
            Connected {new Date(account.created_at).toLocaleDateString()} · last sync{' '}
            {account.last_sync_at
              ? new Date(account.last_sync_at).toLocaleString()
              : 'never'}
          </p>
          <p className="text-xs text-fg-muted">
            {account.emails_ingested_24h} emails in last 24 h ·{' '}
            {account.daily_budget_used_pct.toFixed(0)}% of daily budget
          </p>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <label className="flex items-center gap-3 text-sm text-fg">
          <span>Auto-scan</span>
          <Switch
            checked={effectiveAutoScan}
            onCheckedChange={(next) => patch.mutate({ auto_scan_enabled: next })}
            disabled={patch.isPending}
            ariaLabel={`Toggle auto-scan for ${account.email}`}
          />
          {account.auto_scan_enabled === null ? (
            <span className="text-xs text-fg-muted">(inherit global)</span>
          ) : null}
        </label>
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setSheetOpen(true)}
            aria-label={`More actions for ${account.email}`}
          >
            More…
          </Button>
          <Button
            variant="destructive"
            size="sm"
            onClick={() => setConfirmOpen(true)}
            aria-label={`Disconnect ${account.email}`}
          >
            Disconnect
          </Button>
        </div>
      </div>

    </Card>
  );

  return (
    <div className="relative overflow-hidden rounded-[var(--radius-md)]">
      {isMobile ? (
        <div
          aria-hidden="true"
          className="absolute inset-y-0 right-0 flex w-[160px] items-stretch"
        >
          <button
            type="button"
            onClick={() => {
              patch.mutate({ auto_scan_enabled: false });
              setSwipeRevealed(false);
            }}
            className="flex flex-1 items-center justify-center bg-warn/10 text-xs font-semibold text-warn"
          >
            Pause
          </button>
          <button
            type="button"
            onClick={() => {
              setConfirmOpen(true);
              setSwipeRevealed(false);
            }}
            className="flex flex-1 items-center justify-center bg-danger text-xs font-semibold text-accent-contrast"
          >
            Disconnect
          </button>
        </div>
      ) : null}
      {isMobile ? (
        <Motion
          drag="x"
          dragConstraints={{ left: -SWIPE_REVEAL_PX, right: 0 }}
          dragElastic={0.1}
          animate={{ x: swipeRevealed ? -SWIPE_REVEAL_PX : 0 }}
          onDragEnd={(_event, info) => {
            const next = info.offset.x <= -SWIPE_TRIGGER_PX;
            setSwipeRevealed(next);
          }}
          className="relative bg-bg"
        >
          {cardBody}
        </Motion>
      ) : (
        cardBody
      )}

      <Sheet open={sheetOpen} onClose={() => setSheetOpen(false)} title={account.email}>
        <div className="flex flex-col gap-2">
          <Button
            variant="secondary"
            onClick={() => {
              patch.mutate({
                exclude_from_global_digest: !account.exclude_from_global_digest,
              });
              setSheetOpen(false);
            }}
          >
            {account.exclude_from_global_digest
              ? 'Include in global digest'
              : 'Exclude from global digest'}
          </Button>
          <Button
            variant="secondary"
            onClick={() => {
              reconnect.start();
              setSheetOpen(false);
            }}
          >
            Reconnect account
          </Button>
        </div>
      </Sheet>

      <Dialog
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        title={`Disconnect ${account.email}?`}
        description="This removes Briefed's cached emails, summaries, and job matches for this account. Your Gmail mailbox is not touched."
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmOpen(false)}>
              Keep connected
            </Button>
            <Button
              variant="destructive"
              onClick={() => disconnect.mutate()}
              loading={disconnect.isPending}
            >
              Disconnect
            </Button>
          </>
        }
      >
        <p className="text-sm text-fg-muted">
          You can reconnect later — Briefed will pull history back from Gmail.
        </p>
      </Dialog>
    </div>
  );
}

function applyAccountPatch(
  account: Schemas['ConnectedAccount'],
  body: Schemas['AccountPatchRequest'],
): Schemas['ConnectedAccount'] {
  const next: Schemas['ConnectedAccount'] = {
    ...account,
    auto_scan_enabled: body.auto_scan_enabled ?? account.auto_scan_enabled,
    exclude_from_global_digest:
      body.exclude_from_global_digest ?? account.exclude_from_global_digest,
  };
  if (body.display_name !== undefined) next.display_name = body.display_name;
  return next;
}
