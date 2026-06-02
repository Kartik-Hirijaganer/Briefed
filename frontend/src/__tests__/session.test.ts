import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type * as ApiClient from '../api/client';
import { queryClient } from '../api/queryClient';
import { logoutAndClearBrowserSession } from '../api/session';

const apiMock = vi.hoisted(() => ({ POST: vi.fn() }));
const offlineDeleteMock = vi.hoisted(() => vi.fn());

vi.mock('../api/client', async (importOriginal) => {
  const actual = (await importOriginal()) as typeof ApiClient;
  return { ...actual, api: apiMock };
});

vi.mock('../offline/db', () => ({
  offlineDb: { delete: offlineDeleteMock },
}));

describe('logoutAndClearBrowserSession', () => {
  const originalLocation = window.location;
  const originalCaches = window.caches;

  beforeEach(() => {
    apiMock.POST.mockReset();
    offlineDeleteMock.mockReset();
    offlineDeleteMock.mockResolvedValue(undefined);
    queryClient.clear();
    window.localStorage.clear();
    window.sessionStorage.clear();
  });

  afterEach(() => {
    Object.defineProperty(window, 'location', {
      value: originalLocation,
      configurable: true,
    });
    Object.defineProperty(window, 'caches', {
      value: originalCaches,
      configurable: true,
    });
    queryClient.clear();
    vi.restoreAllMocks();
  });

  it('logs out, clears browser storage, deletes caches, and redirects', async () => {
    const assign = vi.fn();
    const cacheDelete = vi.fn(async (): Promise<boolean> => true);
    Object.defineProperty(window, 'location', {
      value: { ...window.location, assign },
      configurable: true,
    });
    Object.defineProperty(window, 'caches', {
      value: {
        keys: vi.fn(async (): Promise<string[]> => ['briefed-precache', 'briefed-runtime']),
        delete: cacheDelete,
      },
      configurable: true,
    });
    window.localStorage.setItem('briefed-local', '1');
    window.sessionStorage.setItem('briefed-session', '1');
    queryClient.setQueryData(['accounts'], { accounts: [{ id: 'a1' }] });
    apiMock.POST.mockResolvedValue({ response: new Response(null, { status: 204 }) });

    await logoutAndClearBrowserSession();

    expect(apiMock.POST).toHaveBeenCalledWith('/api/v1/auth/logout');
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
    expect(queryClient.getQueryData(['accounts'])).toBeUndefined();
    expect(cacheDelete).toHaveBeenCalledWith('briefed-precache');
    expect(cacheDelete).toHaveBeenCalledWith('briefed-runtime');
    expect(offlineDeleteMock).toHaveBeenCalledTimes(1);
    expect(assign).toHaveBeenCalledWith('/login');
  });
});
