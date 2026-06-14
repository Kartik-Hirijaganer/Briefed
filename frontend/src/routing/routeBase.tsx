import { createContext, useCallback, useContext, useMemo, type ReactNode } from 'react';

/**
 * Supported route bases for reusable app pages.
 */
export type RouteBase = '/app' | '/demo';

/**
 * Context value returned by {@link useRouteBase}.
 */
export interface RouteBaseContextValue {
  /** Base path for links rendered by reusable app pages. */
  readonly base: RouteBase;
}

/**
 * Props for {@link RouteBaseProvider}.
 */
export interface RouteBaseProviderProps {
  /** Base path to prepend to app-relative links. */
  readonly base: RouteBase;
  /** Routed subtree that consumes the base. */
  readonly children: ReactNode;
}

const RouteBaseContext = createContext<RouteBaseContextValue>({ base: '/app' });

/**
 * Provide the active route base for app/demo page reuse.
 *
 * @param props - Component props.
 * @param props.base - Base path for app-relative links.
 * @param props.children - Routed subtree that consumes the base.
 * @returns The route-base context provider.
 */
export function RouteBaseProvider(props: RouteBaseProviderProps): JSX.Element {
  const { base, children } = props;
  const value = useMemo<RouteBaseContextValue>(() => ({ base }), [base]);
  return <RouteBaseContext.Provider value={value}>{children}</RouteBaseContext.Provider>;
}

/**
 * Read the active app/demo route base.
 *
 * @returns Current route-base context.
 */
export function useRouteBase(): RouteBaseContextValue {
  return useContext(RouteBaseContext);
}

/**
 * Build links relative to the active route base.
 *
 * @returns Function that converts a subpath into a rooted app/demo path.
 */
export function useAppPath(): (sub: string) => string {
  const { base } = useRouteBase();
  return useCallback((sub: string): string => buildRoutePath(base, sub), [base]);
}

function buildRoutePath(base: RouteBase, sub: string): string {
  const trimmed = sub.trim();
  if (!trimmed || trimmed === '/') return base;
  if (trimmed.startsWith('?') || trimmed.startsWith('#')) return `${base}${trimmed}`;
  const normalized = trimmed.startsWith('/') ? trimmed.replace(/^\/+/, '') : trimmed;
  return `${base}/${normalized}`;
}
