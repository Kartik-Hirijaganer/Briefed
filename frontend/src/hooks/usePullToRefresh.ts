import { useRef, type TouchEvent } from 'react';

const TRIGGER_DISTANCE_PX = 84;

/**
 * Options for {@link usePullToRefresh}.
 */
export interface PullToRefreshOptions {
  /** Called when the pull distance crosses the trigger threshold. */
  readonly onRefresh: () => void;
  /** Disable gesture handling. */
  readonly disabled?: boolean | undefined;
}

/**
 * Minimal pull-to-refresh gesture for the dashboard surface.
 *
 * @param options - Gesture configuration.
 * @returns Touch handlers to spread on a scroll container.
 */
export function usePullToRefresh(options: PullToRefreshOptions): {
  onTouchStart: (event: TouchEvent<HTMLElement>) => void;
  onTouchMove: (event: TouchEvent<HTMLElement>) => void;
  onTouchEnd: () => void;
} {
  const startY = useRef<number | null>(null);
  const armed = useRef(false);

  return {
    onTouchStart: (event) => {
      if (options.disabled || window.scrollY > 0) return;
      startY.current = event.touches[0]?.clientY ?? null;
      armed.current = false;
    },
    onTouchMove: (event) => {
      if (options.disabled || startY.current === null) return;
      const delta = (event.touches[0]?.clientY ?? startY.current) - startY.current;
      if (delta >= TRIGGER_DISTANCE_PX) armed.current = true;
    },
    onTouchEnd: () => {
      if (!options.disabled && armed.current) options.onRefresh();
      startY.current = null;
      armed.current = false;
    },
  };
}
