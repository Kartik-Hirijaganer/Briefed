import createClient, { type Middleware } from 'openapi-fetch';

import type { paths } from './schema';

import {
  AWS_PAYLOAD_HASH_HEADER,
  computePayloadSha256Hex,
  shouldAttachPayloadHash,
} from './payloadHash';
import { queryClient } from './queryClient';

/**
 * Thrown when any API call returns a non-2xx response. Preserves the HTTP
 * status so TanStack Query's retry policy (see `queryClient.ts`) can skip
 * 4xx's and the 401 redirect middleware can fire.
 */
export class ApiError extends Error {
  /** HTTP status code from the failed response. */
  public readonly status: number;
  /** Optional structured payload the server returned. */
  public readonly detail: unknown;

  /**
   * Build an API error with response metadata.
   *
   * @param message - Human-readable message.
   * @param status - HTTP status code.
   * @param detail - Raw JSON payload.
   */
  public constructor(message: string, status: number, detail: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
    this.name = 'ApiError';
  }
}

/**
 * Thrown before network when demo routes attempt any `/api/*` request.
 */
export class DemoDisabledError extends Error {
  /** API path that was blocked. */
  public readonly path: string;

  /**
   * Build a demo API block error.
   *
   * @param path - Blocked API request path.
   */
  public constructor(path: string) {
    super(`API requests are disabled in demo mode: ${path}`);
    this.path = path;
    this.name = 'DemoDisabledError';
  }
}

const CSRF_HEADER = 'X-CSRF-Token';
const CSRF_COOKIE = 'briefed_csrf';
const LOGIN_PATH = '/login';
const APP_CHILD_PATH_PATTERN = /^\/app\/[^/]/;

const buildLoginRedirectPath = (): string => {
  const pathname = window.location.pathname;
  if (!APP_CHILD_PATH_PATTERN.test(pathname)) return LOGIN_PATH;
  const currentPath = `${pathname}${window.location.search}${window.location.hash}`;
  const params = new URLSearchParams({ next: currentPath });
  return `${LOGIN_PATH}?${params.toString()}`;
};

const readCookie = (name: string): string | undefined => {
  const entries = document.cookie.split('; ');
  for (const entry of entries) {
    const [key, ...rest] = entry.split('=');
    if (key === name) return decodeURIComponent(rest.join('='));
  }
  return undefined;
};

const isDemoRoute = (): boolean => window.location.pathname.startsWith('/demo');

const requestPath = (request: Request): string => {
  const url = new URL(request.url, window.location.origin);
  return url.pathname;
};

const demoBlockMiddleware: Middleware = {
  async onRequest({ request }) {
    const path = requestPath(request);
    if (isDemoRoute() && path.startsWith('/api/')) {
      throw new DemoDisabledError(path);
    }
    return request;
  },
};

const csrfMiddleware: Middleware = {
  async onRequest({ request }) {
    const method = request.method.toUpperCase();
    if (method === 'GET' || method === 'HEAD') return request;
    const token = readCookie(CSRF_COOKIE);
    if (token) request.headers.set(CSRF_HEADER, token);
    return request;
  },
  async onResponse({ response }) {
    if (response.status === 401) {
      queryClient.clear();
      if (!window.location.pathname.startsWith(LOGIN_PATH)) {
        window.location.assign(buildLoginRedirectPath());
      }
    }
    return response;
  },
};

const payloadHashMiddleware: Middleware = {
  async onRequest({ request }) {
    if (!shouldAttachPayloadHash(request.method)) return request;
    const bodyBytes = await request.clone().arrayBuffer();
    request.headers.set(AWS_PAYLOAD_HASH_HEADER, await computePayloadSha256Hex(bodyBytes));
    return request;
  },
};

interface ApiEnvelope<TData> {
  readonly data?: TData;
  readonly error?: unknown;
  readonly response?: Response;
}

/**
 * Typed API client. `credentials: 'include'` sends the session cookie on
 * every request; the CSRF middleware mirrors the double-submit token from
 * the readable `briefed_csrf` cookie into the `X-CSRF-Token` header for
 * state-changing verbs per plan §10 auth flow.
 */
export const api = createClient<paths>({
  baseUrl: import.meta.env.VITE_API_BASE ?? '',
  credentials: 'include',
  headers: { Accept: 'application/json' },
});

api.use(demoBlockMiddleware);
api.use(csrfMiddleware);
api.use(payloadHashMiddleware);

/**
 * Narrow `{ data, error }` envelope returned by openapi-fetch into the
 * success payload, throwing {@link ApiError} on failure. Useful inside
 * TanStack Query `queryFn`s so `useQuery` gets a plain `T` back.
 *
 * @param envelope - Result from `api.GET` / `api.POST` etc.
 * @returns The success payload.
 * @throws {@link ApiError} when the envelope contains an error.
 */
export function unwrap<TData>(envelope: ApiEnvelope<TData>): TData {
  if (envelope.data !== undefined) return envelope.data;
  const status = envelope.response?.status ?? 0;
  throw new ApiError(`API request failed with status ${status}`, status, envelope.error);
}
