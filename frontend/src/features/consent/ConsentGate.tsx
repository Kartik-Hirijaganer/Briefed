import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { Button, Dialog } from '@briefed/ui';

import { acceptLegalConsent } from '../../api/legal';
import { legalConsent } from '../../api/queryKeys';
import { logoutAndClearBrowserSession } from '../../api/session';
import type { Schemas } from '../../api/types';
import { CONSENT_SUMMARY, PRIVACY_POLICY_VERSION, TERMS_VERSION } from '../../content/legal';

const noop = (): void => {};

/**
 * Props for the blocking legal-consent gate.
 */
export interface ConsentGateProps {
  /** Server-reported consent status that required this gate. */
  readonly consent: Schemas['LegalConsentStatus'];
}

/**
 * Blocks authenticated app access until current legal policies are accepted.
 *
 * @param props - Component props.
 * @returns The rendered blocking consent dialog.
 */
export function ConsentGate(props: ConsentGateProps): JSX.Element {
  const { consent } = props;
  const queryClient = useQueryClient();
  const [checked, setChecked] = useState<boolean>(false);
  const [declining, setDeclining] = useState<boolean>(false);

  const acceptMutation = useMutation({
    mutationFn: acceptLegalConsent,
    onSuccess: (status: Schemas['LegalConsentStatus']): void => {
      queryClient.setQueryData(legalConsent(), status);
    },
  });

  const handleAccept = (): void => {
    acceptMutation.mutate({
      privacy_policy_version: PRIVACY_POLICY_VERSION,
      terms_version: TERMS_VERSION,
    });
  };

  const handleDecline = async (): Promise<void> => {
    setDeclining(true);
    try {
      await logoutAndClearBrowserSession();
    } finally {
      setDeclining(false);
    }
  };

  const versionText = `Privacy v${consent.current_privacy_policy_version} / Terms v${consent.current_terms_version}`;

  return (
    <Dialog
      open
      onClose={noop}
      title="Review Briefed's Gmail data terms"
      description="Accept the current Privacy Policy and Terms before Briefed processes Gmail data."
      footer={
        <>
          <Button
            variant="secondary"
            size="md"
            loading={declining}
            disabled={acceptMutation.isPending}
            onClick={() => void handleDecline()}
          >
            Decline & sign out
          </Button>
          <Button
            variant="primary"
            size="md"
            disabled={!checked || declining}
            loading={acceptMutation.isPending}
            onClick={handleAccept}
          >
            Accept
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4 text-sm text-fg">
        <p className="font-medium text-fg">{versionText}</p>
        <ul className="flex flex-col gap-2 pl-5">
          {CONSENT_SUMMARY.map((item) => (
            <li key={item} className="list-disc text-fg-muted">
              {item}
            </li>
          ))}
        </ul>
        <p className="text-fg-muted">
          Read the{' '}
          <a
            className="text-link underline-offset-4 hover:underline"
            href="/privacy"
            target="_blank"
            rel="noreferrer"
          >
            Privacy Policy
          </a>
          ,{' '}
          <a
            className="text-link underline-offset-4 hover:underline"
            href="/terms"
            target="_blank"
            rel="noreferrer"
          >
            Terms
          </a>
          , and{' '}
          <a
            className="text-link underline-offset-4 hover:underline"
            href="/about"
            target="_blank"
            rel="noreferrer"
          >
            About
          </a>
          .
        </p>
        <label className="flex items-start gap-3 rounded-[var(--radius-md)] border border-border bg-bg-muted p-3">
          <input
            type="checkbox"
            checked={checked}
            onChange={(event) => setChecked(event.currentTarget.checked)}
            className="mt-1 h-4 w-4 accent-accent"
          />
          <span>I have read and agree to the Privacy Policy and Terms.</span>
        </label>
        {acceptMutation.isError ? (
          <p role="alert" className="text-sm text-danger">
            Consent could not be saved. Refresh policy pages and try again.
          </p>
        ) : null}
      </div>
    </Dialog>
  );
}
