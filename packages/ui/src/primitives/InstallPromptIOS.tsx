import { Alert } from './Alert';

/**
 * Props for {@link InstallPromptIOS}.
 */
export interface InstallPromptIOSProps {
  /** Invoked when the user dismisses the prompt. */
  readonly onDismiss: () => void;
}

/**
 * Add-to-Home-Screen prompt for iOS Safari. iOS has no
 * `beforeinstallprompt`, so we explain the manual flow — dismiss state
 * persists in Zustand per plan §19.16 §6.
 *
 * @param props - Component props.
 * @returns The rendered banner.
 */
export function InstallPromptIOS(props: InstallPromptIOSProps): JSX.Element {
  return (
    <Alert
      tone="info"
      title="Install Briefed on your iPhone"
      action={
        <button
          type="button"
          onClick={props.onDismiss}
          aria-label="Dismiss install prompt"
          className="text-xs underline underline-offset-4"
        >
          Dismiss
        </button>
      }
    >
      <p>
        Tap <span aria-hidden="true">⎋</span> <strong>Share</strong> then{' '}
        <strong>Add to Home Screen</strong> to get a full-screen experience with offline reading.
      </p>
    </Alert>
  );
}
