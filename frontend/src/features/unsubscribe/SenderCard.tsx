import { Button } from '@briefed/ui';
import { Badge } from '@briefed/ui';

import type { Schemas } from '../../api/types';
import {
  RECENT_SUBJECTS_DISPLAY,
  UNSUBSCRIBE_TAG_LABEL,
  UNSUBSCRIBE_TAG_TONE,
} from '../../config/unsubscribe';
import { openedPercent, senderTags } from './unsubscribeDerived';
import type { ExecuteResultEntry } from './useUnsubscribeData';

/**
 * Props for {@link SenderCard}.
 */
export interface SenderCardProps {
  /** The suggestion row to render. */
  readonly suggestion: Schemas['UnsubscribeSuggestion'];
  /** Whether this card is selected. */
  readonly selected: boolean;
  /** Toggle this card's selection. */
  readonly onToggle: (checked: boolean) => void;
  /**
   * Execute outcome that keeps this card on screen (manual/failed), or
   * null/undefined when none. Drives the in-card follow-up affordance (§5).
   */
  readonly executeResult?: ExecuteResultEntry | null;
  /** Mark a ``manual_required`` row handled (the user finished it). */
  readonly onConfirmManual?: () => void;
  /** Retry a failed execute. */
  readonly onRetry?: () => void;
}

/**
 * One sender row on the unsubscribe page: a select checkbox, an initials
 * avatar, the sender address + domain, recent-subject chips, a stats line, and
 * descriptive tags. The surface tints to the accent when selected.
 *
 * @param props - Component props.
 * @returns The rendered sender card.
 */
export function SenderCard(props: SenderCardProps): JSX.Element {
  const { suggestion, selected, onToggle, executeResult, onConfirmManual, onRetry } = props;
  const recent = suggestion.recent_subjects.slice(0, RECENT_SUBJECTS_DISPLAY);
  const tags = senderTags(suggestion);
  const initial = (suggestion.sender_email[0] ?? '?').toUpperCase();

  return (
    <div
      className={`flex items-start gap-3 rounded-[var(--radius-lg)] border p-4 ${
        selected ? 'border-accent bg-accent/10' : 'border-border bg-surface'
      }`}
    >
      <input
        type="checkbox"
        checked={selected}
        onChange={(event) => onToggle(event.target.checked)}
        aria-label={`Select ${suggestion.sender_email}`}
        className="mt-1 shrink-0"
      />
      <span
        aria-hidden="true"
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent/10 text-sm font-semibold text-accent"
      >
        {initial}
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-fg">{suggestion.sender_email}</p>
            <p className="truncate text-xs text-fg-muted">{suggestion.sender_domain}</p>
          </div>
          <p className="shrink-0 text-xs text-fg-faint">
            {suggestion.frequency_30d}/mo received · {openedPercent(suggestion)}% opened
          </p>
        </div>

        {recent.length > 0 ? (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs uppercase tracking-wide text-fg-faint">Recent</span>
            {recent.map((subject, index) => (
              <Badge key={`${suggestion.id}-recent-${index}`}>
                <span className="block max-w-[16rem] truncate">{subject}</span>
              </Badge>
            ))}
          </div>
        ) : null}

        {tags.length > 0 ? (
          <div className="flex flex-wrap items-center gap-1.5">
            {tags.map((tag) => (
              <Badge key={tag} tone={UNSUBSCRIBE_TAG_TONE[tag]}>
                {UNSUBSCRIBE_TAG_LABEL[tag]}
              </Badge>
            ))}
          </div>
        ) : null}

        {executeResult ? (
          <div className="flex flex-col gap-2 rounded-[var(--radius-md)] border border-border bg-bg-muted p-2 text-xs">
            {executeResult.status === 'manual_required' ? (
              <>
                <p className="text-fg-muted">{executeResult.message}</p>
                <div className="flex flex-wrap items-center gap-3">
                  {executeResult.manualUrl ? (
                    <a
                      href={executeResult.manualUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-link underline-offset-4 hover:underline"
                    >
                      Open unsubscribe page
                    </a>
                  ) : null}
                  <Button variant="secondary" size="sm" onClick={onConfirmManual}>
                    I&apos;ve unsubscribed
                  </Button>
                </div>
              </>
            ) : (
              <>
                <p role="alert" className="text-danger">
                  {executeResult.message}
                </p>
                <div>
                  <Button variant="secondary" size="sm" onClick={onRetry}>
                    Retry
                  </Button>
                </div>
              </>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}
