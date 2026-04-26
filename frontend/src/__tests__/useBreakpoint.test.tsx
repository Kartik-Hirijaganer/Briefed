import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { useBreakpoint } from '../hooks/useBreakpoint';

const setWidth = (px: number): void => {
  Object.defineProperty(window, 'innerWidth', { value: px, configurable: true });
};

describe('useBreakpoint', () => {
  it('returns "sm" below 640px', () => {
    setWidth(500);
    const { result } = renderHook(() => useBreakpoint());
    expect(result.current).toBe('sm');
  });

  it('returns "md" between 640 and 1023', () => {
    setWidth(800);
    const { result } = renderHook(() => useBreakpoint());
    expect(result.current).toBe('md');
  });

  it('returns "lg" at or above 1024', () => {
    setWidth(1280);
    const { result } = renderHook(() => useBreakpoint());
    expect(result.current).toBe('lg');
  });

  it('reacts to a window resize', () => {
    setWidth(1280);
    const { result } = renderHook(() => useBreakpoint());
    expect(result.current).toBe('lg');
    act(() => {
      setWidth(500);
      window.dispatchEvent(new Event('resize'));
    });
    expect(result.current).toBe('sm');
  });
});
