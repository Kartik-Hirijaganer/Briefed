import { useEffect, useState } from 'react';

/**
 * Reactive wrapper around `navigator.onLine` used by freshness-state logic
 * (plan §19.8) and the Scan Now offline guard (plan §19.16 §6).
 *
 * @returns `true` while the browser reports network connectivity.
 */
export function useOnlineStatus(): boolean {
  const [online, setOnline] = useState<boolean>(() =>
    typeof navigator === 'undefined' ? true : navigator.onLine,
  );
  useEffect(() => {
    const on = (): void => setOnline(true);
    const off = (): void => setOnline(false);
    window.addEventListener('online', on);
    window.addEventListener('offline', off);
    return () => {
      window.removeEventListener('online', on);
      window.removeEventListener('offline', off);
    };
  }, []);
  return online;
}
