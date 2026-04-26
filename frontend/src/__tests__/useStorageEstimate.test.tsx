import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { useStorageEstimate } from '../hooks/useStorageEstimate';

const installStorageStub = (estimate: StorageEstimate): void => {
  Object.defineProperty(navigator, 'storage', {
    configurable: true,
    value: { estimate: vi.fn().mockResolvedValue(estimate) },
  });
};

describe('useStorageEstimate (storage quota simulation)', () => {
  afterEach(() => {
    Reflect.deleteProperty(navigator, 'storage');
  });

  it('surfaces a high usage ratio when usage approaches quota', async () => {
    installStorageStub({ usage: 12 * 1024 * 1024, quota: 15 * 1024 * 1024 });

    const { result } = renderHook(() => useStorageEstimate());

    await waitFor(() => {
      expect(result.current.usageRatio).not.toBeNull();
    });
    expect(result.current.usageBytes).toBe(12 * 1024 * 1024);
    expect(result.current.quotaBytes).toBe(15 * 1024 * 1024);
    expect(result.current.usageRatio).toBeCloseTo(0.8, 1);
  });

  it('returns null ratio when navigator.storage.estimate is unsupported', async () => {
    Reflect.deleteProperty(navigator, 'storage');

    const { result } = renderHook(() => useStorageEstimate());

    await new Promise<void>((resolve) => setTimeout(resolve, 0));
    expect(result.current.usageRatio).toBeNull();
    expect(result.current.usageBytes).toBeNull();
    expect(result.current.quotaBytes).toBeNull();
  });

  it('returns null ratio when the browser reports an unknown quota', async () => {
    installStorageStub({ usage: 5 * 1024 * 1024, quota: 0 });

    const { result } = renderHook(() => useStorageEstimate());

    await waitFor(() => {
      expect(result.current.usageBytes).toBe(5 * 1024 * 1024);
    });
    expect(result.current.quotaBytes).toBe(0);
    expect(result.current.usageRatio).toBeNull();
  });
});
