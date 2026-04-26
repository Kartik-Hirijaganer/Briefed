import { useEffect, useState } from 'react';

/**
 * Browser storage estimate used to surface iOS/WebKit quota pressure.
 */
export interface StorageEstimateState {
  /** Usage ratio in `[0, 1]`, or null when unsupported. */
  readonly usageRatio: number | null;
  /** Approximate used bytes. */
  readonly usageBytes: number | null;
  /** Approximate quota bytes. */
  readonly quotaBytes: number | null;
}

/**
 * Read `navigator.storage.estimate()` and refresh periodically.
 *
 * @returns Browser storage pressure state.
 */
export function useStorageEstimate(): StorageEstimateState {
  const [state, setState] = useState<StorageEstimateState>({
    usageRatio: null,
    usageBytes: null,
    quotaBytes: null,
  });

  useEffect(() => {
    let cancelled = false;
    const read = async (): Promise<void> => {
      if (!('storage' in navigator) || !navigator.storage.estimate) return;
      const estimate = await navigator.storage.estimate();
      if (cancelled) return;
      const usage = estimate.usage ?? 0;
      const quota = estimate.quota ?? 0;
      setState({
        usageBytes: usage,
        quotaBytes: quota,
        usageRatio: quota > 0 ? usage / quota : null,
      });
    };
    void read();
    const timer = window.setInterval(() => void read(), 60_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  return state;
}
