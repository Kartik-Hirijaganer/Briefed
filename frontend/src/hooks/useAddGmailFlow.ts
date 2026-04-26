import { useCallback } from 'react';

/**
 * Result of {@link useAddGmailFlow}.
 */
export interface AddGmailFlow {
  /** Backend OAuth start URL (link mode toggles linking onto the active session). */
  readonly startUrl: string;
  /** True when the platform requires escaping the standalone webview (iOS PWA). */
  readonly opensInNewTab: boolean;
  /** Imperative entry point — invoke from a click handler. */
  readonly start: () => void;
}

/**
 * Options for {@link useAddGmailFlow}.
 */
export interface AddGmailFlowOptions {
  /** Treat this as a "link a second account" flow vs. first-time login. */
  readonly link?: boolean;
  /** Path to bounce back to after `/oauth/callback`. */
  readonly returnTo?: string;
}

/**
 * Detects whether the current document is running as an iOS standalone PWA.
 * iOS Safari sets `navigator.standalone` to `true` for added-to-home-screen
 * installs; it is `undefined` everywhere else.
 *
 * @returns True when running as an installed iOS PWA.
 */
export function isIOSStandalone(): boolean {
  if (typeof window === 'undefined') return false;
  const isIOS =
    /iP(hone|ad|od)/i.test(window.navigator.userAgent) ||
    (window.navigator.platform === 'MacIntel' && window.navigator.maxTouchPoints > 1);
  const standalone =
    'standalone' in window.navigator &&
    (window.navigator as Navigator & { standalone?: boolean }).standalone === true;
  return isIOS && standalone;
}

/**
 * Owns the "Add Gmail" entry point so callers don't have to encode the
 * iOS-PWA gotcha (plan §19.16 §6). When running inside a standalone iOS
 * install, the consent screen is escalated to external Safari via
 * `window.open(_blank)`; otherwise we navigate the current tab.
 *
 * @param options - Flow options.
 * @returns Action helpers.
 */
export function useAddGmailFlow(options: AddGmailFlowOptions = {}): AddGmailFlow {
  const params = new URLSearchParams();
  if (options.link) params.set('link', 'true');
  params.set('return_to', options.returnTo ?? '/settings/accounts');
  const startUrl = `/api/v1/oauth/gmail/start?${params.toString()}`;
  const opensInNewTab = isIOSStandalone();

  const start = useCallback((): void => {
    if (opensInNewTab) {
      window.open(startUrl, '_blank', 'noopener');
      return;
    }
    window.location.assign(startUrl);
  }, [opensInNewTab, startUrl]);

  return { startUrl, opensInNewTab, start };
}
