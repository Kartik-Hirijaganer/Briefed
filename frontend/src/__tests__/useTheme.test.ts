import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { useTheme } from '../hooks/useTheme';

interface MutableMediaQuery {
  matches: boolean;
  listeners: Array<(event: MediaQueryListEvent) => void>;
}

const mediaState: MutableMediaQuery = { matches: false, listeners: [] };

function installMatchMedia(): void {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    writable: true,
    value: (query: string) => {
      return {
        matches: mediaState.matches,
        media: query,
        onchange: null,
        addListener: () => undefined,
        removeListener: () => undefined,
        addEventListener: (_event: 'change', listener: (event: MediaQueryListEvent) => void) => {
          mediaState.listeners.push(listener);
        },
        removeEventListener: (_event: 'change', listener: (event: MediaQueryListEvent) => void) => {
          mediaState.listeners = mediaState.listeners.filter((l) => l !== listener);
        },
        dispatchEvent: () => false,
      };
    },
  });
}

function flipMedia(matches: boolean): void {
  mediaState.matches = matches;
  for (const listener of [...mediaState.listeners]) {
    listener({ matches } as MediaQueryListEvent);
  }
}

describe('useTheme', () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.removeAttribute('data-theme');
    mediaState.matches = false;
    mediaState.listeners = [];
    installMatchMedia();
  });

  afterEach(() => {
    window.localStorage.clear();
    mediaState.listeners = [];
  });

  it('defaults to system + resolves via matchMedia', () => {
    mediaState.matches = false;
    const { result } = renderHook(() => useTheme());
    expect(result.current.preference).toBe('system');
    expect(result.current.resolved).toBe('light');
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');
  });

  it('switches resolved theme when the system media query flips', () => {
    const { result } = renderHook(() => useTheme());
    act(() => flipMedia(true));
    expect(result.current.resolved).toBe('dark');
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
  });

  it('persists the preference to localStorage on setPreference', () => {
    const { result } = renderHook(() => useTheme());
    act(() => result.current.setPreference('dark'));
    expect(window.localStorage.getItem('briefed.theme')).toBe('dark');
    expect(result.current.preference).toBe('dark');
    expect(result.current.resolved).toBe('dark');
  });

  it('resyncs after profile load via hydrateFromProfile', () => {
    const { result } = renderHook(() => useTheme());
    expect(result.current.preference).toBe('system');
    act(() => result.current.hydrateFromProfile('dark'));
    expect(result.current.preference).toBe('dark');
    expect(window.localStorage.getItem('briefed.theme')).toBe('dark');
  });
});
