import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useInstallPrompt } from '../hooks/useInstallPrompt';

const IOS_UA =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Safari/604.1';

const stubMatchMedia = (standalone: boolean): void => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    configurable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: query === '(display-mode: standalone)' ? standalone : false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
};

const setNavigatorIOS = (overrides: Partial<Navigator> = {}): void => {
  Object.defineProperty(window.navigator, 'userAgent', { value: IOS_UA, configurable: true });
  Object.defineProperty(window.navigator, 'platform', { value: 'iPhone', configurable: true });
  Object.defineProperty(window.navigator, 'maxTouchPoints', { value: 5, configurable: true });
  Object.assign(window.navigator, overrides);
};

describe('useInstallPrompt', () => {
  const originalMatchMedia = window.matchMedia;
  const originalUA = window.navigator.userAgent;
  const originalPlatform = window.navigator.platform;

  beforeEach(() => {
    window.localStorage.clear();
    stubMatchMedia(false);
    setNavigatorIOS();
  });

  afterEach(() => {
    Object.defineProperty(window, 'matchMedia', {
      value: originalMatchMedia,
      configurable: true,
      writable: true,
    });
    Object.defineProperty(window.navigator, 'userAgent', {
      value: originalUA,
      configurable: true,
    });
    Object.defineProperty(window.navigator, 'platform', {
      value: originalPlatform,
      configurable: true,
    });
  });

  it('shows the prompt on iOS Safari when not dismissed and not standalone', () => {
    const { result } = renderHook(() => useInstallPrompt());
    expect(result.current.showIOSInstallPrompt).toBe(true);
  });

  it('hides the prompt when running standalone', () => {
    stubMatchMedia(true);
    const { result } = renderHook(() => useInstallPrompt());
    expect(result.current.showIOSInstallPrompt).toBe(false);
  });

  it('hides the prompt when previously dismissed', () => {
    window.localStorage.setItem('briefed-ios-install-dismissed', 'true');
    const { result } = renderHook(() => useInstallPrompt());
    expect(result.current.showIOSInstallPrompt).toBe(false);
  });

  it('persists the dismiss flag and clears the prompt state', () => {
    const { result } = renderHook(() => useInstallPrompt());
    expect(result.current.showIOSInstallPrompt).toBe(true);
    act(() => result.current.dismissIOSInstallPrompt());
    expect(result.current.showIOSInstallPrompt).toBe(false);
    expect(window.localStorage.getItem('briefed-ios-install-dismissed')).toBe('true');
  });

  it('does not show the prompt on a non-iOS user agent', () => {
    Object.defineProperty(window.navigator, 'userAgent', {
      value: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120',
      configurable: true,
    });
    Object.defineProperty(window.navigator, 'platform', {
      value: 'Win32',
      configurable: true,
    });
    const { result } = renderHook(() => useInstallPrompt());
    expect(result.current.showIOSInstallPrompt).toBe(false);
  });
});
