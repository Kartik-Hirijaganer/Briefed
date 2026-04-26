import { renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { usePullToRefresh } from '../hooks/usePullToRefresh';

type Handlers = ReturnType<typeof usePullToRefresh>;

const touch = (clientY: number): { touches: Array<{ clientY: number }> } => ({
  touches: [{ clientY }],
});

const setScrollY = (value: number): void => {
  Object.defineProperty(window, 'scrollY', { value, configurable: true });
};

describe('usePullToRefresh', () => {
  it('invokes onRefresh when the pull crosses the trigger threshold', () => {
    setScrollY(0);
    const onRefresh = vi.fn();
    const { result } = renderHook(() => usePullToRefresh({ onRefresh }));
    const h = result.current as Handlers & {
      onTouchStart: (e: ReturnType<typeof touch>) => void;
      onTouchMove: (e: ReturnType<typeof touch>) => void;
      onTouchEnd: () => void;
    };
    h.onTouchStart(touch(10) as never);
    h.onTouchMove(touch(120) as never);
    h.onTouchEnd();
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it('does not fire when the pull stays under the threshold', () => {
    setScrollY(0);
    const onRefresh = vi.fn();
    const { result } = renderHook(() => usePullToRefresh({ onRefresh }));
    const h = result.current as Handlers & {
      onTouchStart: (e: ReturnType<typeof touch>) => void;
      onTouchMove: (e: ReturnType<typeof touch>) => void;
      onTouchEnd: () => void;
    };
    h.onTouchStart(touch(10) as never);
    h.onTouchMove(touch(40) as never);
    h.onTouchEnd();
    expect(onRefresh).not.toHaveBeenCalled();
  });

  it('skips the gesture when disabled', () => {
    setScrollY(0);
    const onRefresh = vi.fn();
    const { result } = renderHook(() => usePullToRefresh({ onRefresh, disabled: true }));
    const h = result.current as Handlers & {
      onTouchStart: (e: ReturnType<typeof touch>) => void;
      onTouchMove: (e: ReturnType<typeof touch>) => void;
      onTouchEnd: () => void;
    };
    h.onTouchStart(touch(10) as never);
    h.onTouchMove(touch(200) as never);
    h.onTouchEnd();
    expect(onRefresh).not.toHaveBeenCalled();
  });

  it('skips the gesture when the page is already scrolled', () => {
    setScrollY(120);
    const onRefresh = vi.fn();
    const { result } = renderHook(() => usePullToRefresh({ onRefresh }));
    const h = result.current as Handlers & {
      onTouchStart: (e: ReturnType<typeof touch>) => void;
      onTouchMove: (e: ReturnType<typeof touch>) => void;
      onTouchEnd: () => void;
    };
    h.onTouchStart(touch(10) as never);
    h.onTouchMove(touch(200) as never);
    h.onTouchEnd();
    expect(onRefresh).not.toHaveBeenCalled();
  });
});
