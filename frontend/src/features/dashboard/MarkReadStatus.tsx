import { Alert, Button } from '@briefed/ui';

import { ApiError } from '../../api/client';
import type { Schemas } from '../../api/types';
import { useDemoMode } from '../../demo/DemoModeProvider';
import { useAddGmailFlow } from '../../hooks/useAddGmailFlow';
import type { MarkReadMutation } from './useDashboardData';

/**
 * Props for {@link MarkReadStatus}.
 */
export interface MarkReadStatusProps {
  /** The mark-read mutation whose state drives the feedback banner. */
  readonly mutation: MarkReadMutation;
  /** Path to return to after a Gmail reconnect. */
  readonly reconnectReturnTo: string;
}

/**
 * Render mark-read success/failure feedback, including the Gmail
 * re-authorization recovery flow.
 *
 * @param props - Component props.
 * @returns The rendered status region, or `null` when idle.
 */
export function MarkReadStatus(props: MarkReadStatusProps): JSX.Element | null {
  const { mutation, reconnectReturnTo } = props;
  const { isDemo } = useDemoMode();
  const reconnect = useAddGmailFlow({ link: true, returnTo: reconnectReturnTo });
  const errorEnvelope = mutation.error ? apiErrorEnvelope(mutation.error) : null;
  if (errorEnvelope?.code === 'gmail_reauthorization_required') {
    return (
      <Alert tone="warn" title="Reconnect Gmail to mark mail read">
        <div className="flex flex-col gap-3">
          <p>{errorEnvelope.message}</p>
          <div>
            <Button
              variant="secondary"
              size="sm"
              onClick={reconnect.start}
              disabled={isDemo}
              title={isDemo ? 'Disabled in demo' : undefined}
            >
              {isDemo ? 'Disabled in demo' : 'Reconnect Gmail'}
            </Button>
          </div>
        </div>
      </Alert>
    );
  }
  if (mutation.isError) {
    return (
      <Alert tone="danger" title="Could not mark mail read">
        <p>{mutation.error.message}</p>
      </Alert>
    );
  }
  if (mutation.data && mutation.data.failed.length > 0) {
    return (
      <Alert tone="warn" title="Some messages need attention">
        <p>
          {mutation.data.marked} marked read; {mutation.data.failed.length} could not be updated.
        </p>
      </Alert>
    );
  }
  if (mutation.data && mutation.data.marked > 0) {
    return (
      <Alert tone="success" title="Marked read">
        <p>
          {mutation.data.marked} message{mutation.data.marked === 1 ? '' : 's'} cleared.
        </p>
      </Alert>
    );
  }
  return null;
}

/**
 * Extract an Aegis API error envelope from an API error instance.
 *
 * @param error - Mutation error raised by `unwrap`.
 * @returns The typed envelope, or `null` for non-API errors.
 */
function apiErrorEnvelope(error: Error): Schemas['ErrorEnvelope'] | null {
  if (!(error instanceof ApiError)) return null;
  if (typeof error.detail !== 'object' || error.detail === null) return null;
  const detail = error.detail as Record<string, unknown>;
  if (
    typeof detail.code !== 'string' ||
    typeof detail.message !== 'string' ||
    typeof detail.requestId !== 'string'
  ) {
    return null;
  }
  const details =
    typeof detail.details === 'object' && detail.details !== null
      ? (detail.details as Record<string, unknown>)
      : {};
  return {
    code: detail.code,
    message: detail.message,
    details,
    requestId: detail.requestId,
  };
}
