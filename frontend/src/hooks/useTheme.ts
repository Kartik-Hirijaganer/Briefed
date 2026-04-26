/**
 * Theme preference hook (Track C — Phase I.6).
 *
 * Reads `localStorage('briefed.theme')`, falls back to `'system'`, and
 * mirrors the resolved theme to `<html data-theme="...">` plus
 * `<meta name="theme-color">` so the browser chrome (PWA status bar)
 * matches the canvas.
 *
 * When the preference is `'system'`, listens on
 * `window.matchMedia('(prefers-color-scheme: dark)')` and reflows on
 * flip. Once an authenticated profile loads, calling
 * `hydrateFromProfile(serverPref)` lets the server-side preference win
 * (see `useTheme.test.ts` for the precedence rules).
 *
 * Mutating preference via `setPreference()` writes localStorage
 * synchronously so the next reload's inline FOUC script picks up the
 * value before CSS paints.
 */

import { useCallback, useEffect, useMemo, useSyncExternalStore } from 'react';

/**
 *
 */
export type ThemePreference = 'system' | 'light' | 'dark';
/**
 *
 */
export type ResolvedTheme = 'light' | 'dark';

const STORAGE_KEY = 'briefed.theme';
const META_THEME_COLOR = { light: '#fafafb', dark: '#0a0a0f' } as const;

/**
 * Return the dark-mode media query, or `null` outside browser contexts
 * (jsdom returns a stub but vitest test setups occasionally null it).
 *
 * @returns The media query list, or null when matchMedia is unavailable.
 */
function darkMediaQuery(): MediaQueryList | null {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return null;
  return window.matchMedia('(prefers-color-scheme: dark)');
}

/**
 * Read the persisted preference. Returns `'system'` when storage is
 * empty or unreadable (private mode, blocked storage, SSR).
 *
 * @returns The persisted preference.
 */
function readStoredPreference(): ThemePreference {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw === 'light' || raw === 'dark' || raw === 'system') return raw;
  } catch {
    // Ignore read failures and fall through to the default.
  }
  return 'system';
}

/**
 * Resolve a preference into a concrete `'light' | 'dark'` mode using
 * the system media query when needed.
 *
 * @param pref - Preference to resolve.
 * @returns The concrete mode that should paint right now.
 */
function resolvePreference(pref: ThemePreference): ResolvedTheme {
  if (pref === 'light' || pref === 'dark') return pref;
  const mq = darkMediaQuery();
  return mq?.matches ? 'dark' : 'light';
}

/**
 * Mirror the resolved theme to the document root + `<meta name="theme-color">`.
 *
 * @param resolved - Concrete `light` or `dark` mode.
 */
function applyResolvedTheme(resolved: ResolvedTheme): void {
  if (typeof document === 'undefined') return;
  document.documentElement.setAttribute('data-theme', resolved);
  const meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', META_THEME_COLOR[resolved]);
}

/**
 * Subscribe + snapshot pair for `useSyncExternalStore`. Notifies on
 * `storage` events (cross-tab) and on dark-media-query flips so the
 * snapshot reads stay correct.
 *
 * @param notify - Reactivity callback wired by React.
 * @returns Cleanup that detaches both listeners.
 */
function subscribeStore(notify: () => void): () => void {
  const onStorage = (event: StorageEvent): void => {
    if (event.key === null || event.key === STORAGE_KEY) notify();
  };
  const mq = darkMediaQuery();
  const onMedia = (): void => notify();
  if (typeof window !== 'undefined') {
    window.addEventListener('storage', onStorage);
  }
  mq?.addEventListener?.('change', onMedia);
  return () => {
    if (typeof window !== 'undefined') window.removeEventListener('storage', onStorage);
    mq?.removeEventListener?.('change', onMedia);
  };
}

interface ThemeSnapshot {
  readonly preference: ThemePreference;
  readonly resolved: ResolvedTheme;
}

let cachedSnapshot: ThemeSnapshot = { preference: 'system', resolved: 'light' };

/**
 * Snapshot of the theme state, returned with a stable reference until
 * the underlying preference or media-query result actually changes.
 * `useSyncExternalStore` bails out of re-renders only when the snapshot
 * identity is preserved — recomputing a fresh object every call sends
 * React into an update loop.
 *
 * @returns The current snapshot (cached identity when unchanged).
 */
function snapshotStore(): ThemeSnapshot {
  const preference = readStoredPreference();
  const resolved = resolvePreference(preference);
  if (cachedSnapshot.preference === preference && cachedSnapshot.resolved === resolved) {
    return cachedSnapshot;
  }
  cachedSnapshot = { preference, resolved };
  return cachedSnapshot;
}

/** Server-side fallback — light mode, no-op. */
const SERVER_SNAPSHOT: ThemeSnapshot = { preference: 'system', resolved: 'light' };

/**
 * Hook return shape.
 *
 * @property preference - User-chosen preference: `'system' | 'light' | 'dark'`.
 * @property resolved - Currently-painted concrete mode: `'light' | 'dark'`.
 * @property setPreference - Persist a new preference and reflow.
 * @property hydrateFromProfile - Server-side preference override; called
 *   once the authenticated profile resolves.
 */
export interface UseThemeResult {
  readonly preference: ThemePreference;
  readonly resolved: ResolvedTheme;
  readonly setPreference: (next: ThemePreference) => void;
  readonly hydrateFromProfile: (serverPref: ThemePreference | null | undefined) => void;
}

/**
 * Track + control the active UI theme.
 *
 * @returns The reactive theme state and mutators.
 */
export function useTheme(): UseThemeResult {
  const state = useSyncExternalStore(subscribeStore, snapshotStore, () => SERVER_SNAPSHOT);

  // Reflow `<html data-theme>` and `<meta name="theme-color">` after
  // every commit. The inline FOUC script handles the first paint; this
  // keeps subsequent updates in lockstep with React state.
  useEffect(() => {
    applyResolvedTheme(state.resolved);
  }, [state.resolved]);

  const setPreference = useCallback((next: ThemePreference): void => {
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Storage may be disabled (private mode, third-party iframe).
      // The DOM still updates so the current session honors the choice.
    }
    applyResolvedTheme(resolvePreference(next));
    // Notify other tabs immediately — the `storage` event only fires
    // cross-tab, so dispatch a same-tab `storage` event so the
    // subscriber-snapshot pair re-reads the new preference.
    if (typeof window !== 'undefined') {
      try {
        window.dispatchEvent(new StorageEvent('storage', { key: STORAGE_KEY, newValue: next }));
      } catch {
        // StorageEvent constructor is unavailable in some test envs;
        // a forced read is the fallback.
        window.dispatchEvent(new Event('storage'));
      }
    }
  }, []);

  const hydrateFromProfile = useCallback(
    (serverPref: ThemePreference | null | undefined): void => {
      if (serverPref !== 'system' && serverPref !== 'light' && serverPref !== 'dark') return;
      const current = readStoredPreference();
      if (current === serverPref) return;
      setPreference(serverPref);
    },
    [setPreference],
  );

  return useMemo(
    () => ({
      preference: state.preference,
      resolved: state.resolved,
      setPreference,
      hydrateFromProfile,
    }),
    [state.preference, state.resolved, setPreference, hydrateFromProfile],
  );
}

/**
 * Test-only escape hatch into module-private helpers.
 *
 * @internal
 */
export const _internals = {
  STORAGE_KEY,
  readStoredPreference,
  resolvePreference,
  applyResolvedTheme,
};
