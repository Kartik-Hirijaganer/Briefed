import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { useOnlineStatus } from '../hooks/useOnlineStatus';

const setOnline = (value: boolean): void => {
  Object.defineProperty(window.navigator, 'onLine', {
    value,
    configurable: true,
  });
};

describe('useOnlineStatus', () => {
  afterEach(() => setOnline(true));

  it('reflects the navigator.onLine snapshot at mount', () => {
    setOnline(false);
    const { result } = renderHook(() => useOnlineStatus());
    expect(result.current).toBe(false);
  });

  it('flips to true when an "online" event fires', () => {
    setOnline(false);
    const { result } = renderHook(() => useOnlineStatus());
    act(() => {
      window.dispatchEvent(new Event('online'));
    });
    expect(result.current).toBe(true);
  });

  it('flips to false when an "offline" event fires', () => {
    setOnline(true);
    const { result } = renderHook(() => useOnlineStatus());
    act(() => {
      window.dispatchEvent(new Event('offline'));
    });
    expect(result.current).toBe(false);
  });
});
