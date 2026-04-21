import { useCallback, useEffect, useState } from 'react';

const DISMISSED_KEY = 'briefed-ios-install-dismissed';

/**
 * PWA install-prompt state for iOS Safari.
 *
 * @returns Whether to show the manual iOS add-to-home-screen banner.
 */
export function useInstallPrompt(): {
  showIOSInstallPrompt: boolean;
  dismissIOSInstallPrompt: () => void;
} {
  const [showIOSInstallPrompt, setShowIOSInstallPrompt] = useState(false);

  useEffect(() => {
    const dismissed = window.localStorage.getItem(DISMISSED_KEY) === 'true';
    if (dismissed || isStandaloneDisplay()) return;
    setShowIOSInstallPrompt(isIOSWebKit());
  }, []);

  const dismissIOSInstallPrompt = useCallback((): void => {
    window.localStorage.setItem(DISMISSED_KEY, 'true');
    setShowIOSInstallPrompt(false);
  }, []);

  return { showIOSInstallPrompt, dismissIOSInstallPrompt };
}

function isStandaloneDisplay(): boolean {
  const navigatorWithStandalone = navigator as Navigator & { readonly standalone?: boolean };
  return (
    window.matchMedia('(display-mode: standalone)').matches ||
    Boolean(navigatorWithStandalone.standalone)
  );
}

function isIOSWebKit(): boolean {
  const userAgent = navigator.userAgent;
  const platform = navigator.platform;
  const iOSDevice = /iPad|iPhone|iPod/.test(platform);
  const iPadDesktopMode = platform === 'MacIntel' && navigator.maxTouchPoints > 1;
  const safari = /Safari/.test(userAgent) && !/CriOS|FxiOS|EdgiOS/.test(userAgent);
  return (iOSDevice || iPadDesktopMode) && safari;
}
