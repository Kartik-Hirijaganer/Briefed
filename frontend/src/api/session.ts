import { api, ApiError } from './client';
import { queryClient } from './queryClient';
import { offlineDb } from '../offline/db';

const LOGIN_PATH = '/login';

/**
 * Logs out the current user and removes browser-side Briefed state.
 *
 * @returns A promise that resolves after local browser state is cleared and
 * the browser has been redirected to the login page.
 * @throws ApiError when the server does not accept the logout request.
 */
export async function logoutAndClearBrowserSession(): Promise<void> {
  const result = await api.POST('/api/v1/auth/logout');
  if (result.error !== undefined || result.response?.ok !== true) {
    const status = result.response?.status ?? 0;
    throw new ApiError(`Logout failed with status ${status}`, status, result.error);
  }
  await clearLocalBrowserState();
  window.location.assign(LOGIN_PATH);
}

/**
 * Clears in-memory, persistent, and Cache Storage state owned by Briefed.
 *
 * @returns A promise that resolves once best-effort cleanup has completed.
 */
async function clearLocalBrowserState(): Promise<void> {
  queryClient.clear();
  window.localStorage.clear();
  window.sessionStorage.clear();
  await clearCacheStorage();
  await offlineDb.delete();
}

/**
 * Deletes all Cache Storage buckets for the current origin when available.
 *
 * @returns A promise that resolves once cache deletion attempts complete.
 */
async function clearCacheStorage(): Promise<void> {
  if (!('caches' in window)) return;
  const cacheNames = await window.caches.keys();
  await Promise.all(cacheNames.map((cacheName) => window.caches.delete(cacheName)));
}
