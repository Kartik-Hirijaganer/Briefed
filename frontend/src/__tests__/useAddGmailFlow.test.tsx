import { renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { useAddGmailFlow } from '../hooks/useAddGmailFlow';

describe('useAddGmailFlow', () => {
  const originalUserAgent = window.navigator.userAgent;

  afterEach(() => {
    Object.defineProperty(window.navigator, 'userAgent', {
      value: originalUserAgent,
      configurable: true,
    });
    Object.defineProperty(window.navigator, 'standalone', {
      value: undefined,
      configurable: true,
    });
    vi.restoreAllMocks();
  });

  it('builds an OAuth start URL that respects link + returnTo', () => {
    const { result } = renderHook(() =>
      useAddGmailFlow({ link: true, returnTo: '/settings/accounts' }),
    );
    expect(result.current.startUrl).toBe(
      '/api/v1/oauth/gmail/start?link=true&return_to=%2Fsettings%2Faccounts',
    );
    expect(result.current.opensInNewTab).toBe(false);
  });

  it('navigates the current tab when not running as iOS PWA', () => {
    const assign = vi.fn();
    Object.defineProperty(window, 'location', {
      value: { ...window.location, assign },
      configurable: true,
    });
    const { result } = renderHook(() => useAddGmailFlow({ returnTo: '/' }));
    result.current.start();
    expect(assign).toHaveBeenCalledWith('/api/v1/oauth/gmail/start?return_to=%2F');
  });

  it('escapes to external Safari when running as iOS PWA', () => {
    Object.defineProperty(window.navigator, 'userAgent', {
      value: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15',
      configurable: true,
    });
    Object.defineProperty(window.navigator, 'standalone', {
      value: true,
      configurable: true,
    });
    const open = vi.spyOn(window, 'open').mockReturnValue(null);
    const { result } = renderHook(() => useAddGmailFlow({ returnTo: '/' }));
    result.current.start();
    expect(result.current.opensInNewTab).toBe(true);
    expect(open).toHaveBeenCalledWith(
      '/api/v1/oauth/gmail/start?return_to=%2F',
      '_blank',
      'noopener',
    );
  });
});
