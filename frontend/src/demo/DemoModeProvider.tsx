import { createContext, useContext, useMemo, type ReactNode } from 'react';

/**
 * Demo-mode context consumed by reused app surfaces.
 */
export interface DemoModeContextValue {
  /** Whether the current route is running against synthetic demo data. */
  readonly isDemo: boolean;
}

/**
 * Props for {@link DemoModeProvider}.
 */
export interface DemoModeProviderProps {
  /** Routed subtree that should behave as read-only demo UI. */
  readonly children: ReactNode;
}

const DemoModeContext = createContext<DemoModeContextValue>({ isDemo: false });

/**
 * Mark a route subtree as synthetic demo mode.
 *
 * @param props - Component props.
 * @param props.children - Routed subtree rendered under `/demo`.
 * @returns The demo-mode context provider.
 */
export function DemoModeProvider(props: DemoModeProviderProps): JSX.Element {
  const value = useMemo<DemoModeContextValue>(() => ({ isDemo: true }), []);
  return <DemoModeContext.Provider value={value}>{props.children}</DemoModeContext.Provider>;
}

/**
 * Read whether the current subtree is running in demo mode.
 *
 * @returns Current demo-mode state.
 */
export function useDemoMode(): DemoModeContextValue {
  return useContext(DemoModeContext);
}
