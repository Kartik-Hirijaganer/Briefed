import { afterEach, describe, expect, it, vi } from 'vitest';

import { api, DemoDisabledError } from '../api/client';

const jsonResponse = new Response(
  JSON.stringify({
    run_id: '00000000-0000-4000-8000-000000000000',
    accounts_queued: 1,
  }),
  { status: 202, headers: { 'Content-Type': 'application/json' } },
);

describe('api client payload hash middleware', () => {
  const originalLocation = window.location;

  afterEach(() => {
    Object.defineProperty(window, 'location', {
      value: originalLocation,
      configurable: true,
    });
    vi.restoreAllMocks();
  });

  it('hashes the exact serialized JSON body for POST requests', async () => {
    const requests: Request[] = [];
    const fetchSpy = vi.fn(async (input: RequestInfo | URL): Promise<Response> => {
      requests.push(input as Request);
      return jsonResponse.clone();
    });

    await api.POST('/api/v1/runs', {
      baseUrl: 'https://briefed.test',
      fetch: fetchSpy as unknown as typeof fetch,
      body: {
        kind: 'manual',
        mode: 'incremental',
        include_user_overrides: false,
      },
    });

    const request = requests[0]!;
    await expect(request.clone().text()).resolves.toBe(
      '{"kind":"manual","mode":"incremental","include_user_overrides":false}',
    );
    expect(request.headers.get('x-amz-content-sha256')).toBe(
      'dc68f67c8453285f0571edfffaf9969bccfcf64f8798db21050bd40d6da884a8',
    );
  });

  it('sends the empty payload hash for bodyless POST requests', async () => {
    const requests: Request[] = [];
    const fetchSpy = vi.fn(async (input: RequestInfo | URL): Promise<Response> => {
      requests.push(input as Request);
      return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } });
    });

    await api.POST('/api/v1/unsubscribes/{suggestion_id}/confirm', {
      baseUrl: 'https://briefed.test',
      fetch: fetchSpy as unknown as typeof fetch,
      params: { path: { suggestion_id: 'suggestion-1' } },
    });

    const request = requests[0]!;
    await expect(request.clone().text()).resolves.toBe('');
    expect(request.headers.get('x-amz-content-sha256')).toBe(
      'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    );
  });

  it('redirects unauthenticated responses to login with the current path preserved', async () => {
    const assign = vi.fn();
    Object.defineProperty(window, 'location', {
      value: {
        ...window.location,
        pathname: '/app/settings/accounts',
        search: '?tab=accounts',
        hash: '#add',
        assign,
      },
      configurable: true,
    });
    const fetchSpy = vi.fn(async (): Promise<Response> => {
      return new Response(JSON.stringify({ detail: 'not authenticated' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      });
    });

    await api.GET('/api/v1/accounts', {
      baseUrl: 'https://briefed.test',
      fetch: fetchSpy as unknown as typeof fetch,
    });

    expect(assign).toHaveBeenCalledWith(
      '/login?next=%2Fapp%2Fsettings%2Faccounts%3Ftab%3Daccounts%23add',
    );
  });

  it('redirects unauthenticated /app home responses to login without next', async () => {
    const assign = vi.fn();
    Object.defineProperty(window, 'location', {
      value: {
        ...window.location,
        pathname: '/app',
        search: '',
        hash: '',
        assign,
      },
      configurable: true,
    });
    const fetchSpy = vi.fn(async (): Promise<Response> => {
      return new Response(JSON.stringify({ detail: 'not authenticated' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      });
    });

    await api.GET('/api/v1/accounts', {
      baseUrl: 'https://briefed.test',
      fetch: fetchSpy as unknown as typeof fetch,
    });

    expect(assign).toHaveBeenCalledWith('/login');
  });

  it('blocks every demo API GET before fetch or login redirect', async () => {
    const assign = vi.fn();
    Object.defineProperty(window, 'location', {
      value: {
        ...window.location,
        pathname: '/demo/history',
        search: '',
        hash: '',
        assign,
      },
      configurable: true,
    });
    const fetchSpy = vi.fn(async (): Promise<Response> => {
      return new Response(JSON.stringify({ accounts: [] }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    });

    await expect(
      api.GET('/api/v1/accounts', {
        baseUrl: 'https://briefed.test',
        fetch: fetchSpy as unknown as typeof fetch,
      }),
    ).rejects.toBeInstanceOf(DemoDisabledError);

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(assign).not.toHaveBeenCalled();
  });

  it('blocks demo API mutations before fetch or login redirect', async () => {
    const assign = vi.fn();
    Object.defineProperty(window, 'location', {
      value: {
        ...window.location,
        pathname: '/demo',
        search: '',
        hash: '',
        assign,
      },
      configurable: true,
    });
    const fetchSpy = vi.fn(async (): Promise<Response> => {
      return jsonResponse.clone();
    });

    await expect(
      api.POST('/api/v1/runs', {
        baseUrl: 'https://briefed.test',
        fetch: fetchSpy as unknown as typeof fetch,
        body: {
          kind: 'manual',
          mode: 'incremental',
          include_user_overrides: false,
        },
      }),
    ).rejects.toBeInstanceOf(DemoDisabledError);

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(assign).not.toHaveBeenCalled();
  });
});
