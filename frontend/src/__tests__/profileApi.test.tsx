import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  fetchProfile,
  fetchSchedule,
  patchProfile,
  patchSchedule,
} from '../features/settings/profileApi';

type FetchMock = ReturnType<typeof vi.fn>;

const mockFetch = (status = 200, body: unknown = {}): FetchMock => {
  const fn = vi.fn(
    async () =>
      new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
      }),
  );
  globalThis.fetch = fn as unknown as typeof fetch;
  return fn;
};

const setCsrfCookie = (token: string | null): void => {
  Object.defineProperty(document, 'cookie', {
    configurable: true,
    get: () => (token ? `briefed_csrf=${encodeURIComponent(token)}` : ''),
    set(_value: string) {
      // No-op stub — tests only exercise the read path.
    },
  });
};

describe('profileApi', () => {
  beforeEach(() => setCsrfCookie(null));
  afterEach(() => vi.restoreAllMocks());

  it('GETs /api/v1/profile/me and returns the body', async () => {
    const fetchSpy = mockFetch(200, { display_name: 'Alex' });
    const profile = await fetchProfile();
    expect(profile).toEqual({ display_name: 'Alex' });
    const [, init] = fetchSpy.mock.calls[0]!;
    expect(init?.credentials).toBe('same-origin');
  });

  it('GETs /api/v1/profile/me/schedule', async () => {
    mockFetch(200, { schedule_frequency: 'once_daily' });
    const schedule = await fetchSchedule();
    expect(schedule).toEqual({ schedule_frequency: 'once_daily' });
  });

  it('PATCHes the profile with the JSON body and CSRF header when cookie is set', async () => {
    setCsrfCookie('csrf-token');
    const fetchSpy = mockFetch(200, { display_name: 'Updated' });
    const result = await patchProfile({ display_name: 'Updated' });
    expect(result).toEqual({ display_name: 'Updated' });
    const [, init] = fetchSpy.mock.calls[0]!;
    expect(init?.method).toBe('PATCH');
    expect(JSON.parse(String(init?.body))).toEqual({ display_name: 'Updated' });
    const headers = init?.headers as Headers;
    expect(headers.get('X-CSRF-Token')).toBe('csrf-token');
    expect(headers.get('x-amz-content-sha256')).toBe(
      '6e1c3f5311c2d4c49eff08c5727a6333ee9077146ad70f0bb8f46f4762551895',
    );
  });

  it('PATCHes the schedule and returns the body', async () => {
    mockFetch(200, { schedule_frequency: 'twice_daily' });
    const result = await patchSchedule({ schedule_frequency: 'twice_daily' });
    expect(result).toEqual({ schedule_frequency: 'twice_daily' });
    const [, init] = (globalThis.fetch as FetchMock).mock.calls[0]!;
    const headers = init?.headers as Headers;
    expect(headers.get('x-amz-content-sha256')).toBe(
      '91634c9e96706f1a3bc7bbffbe6fc7d4d0f329b1068cb2eb9d3ce4e253764bcc',
    );
  });

  it('throws on a non-2xx response', async () => {
    mockFetch(500, { detail: 'boom' });
    await expect(fetchProfile()).rejects.toThrow(/Profile API request failed \(500\)/);
  });
});
