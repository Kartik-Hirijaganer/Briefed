import { QueryClientProvider } from '@tanstack/react-query';
import { Outlet } from 'react-router-dom';

import { Badge } from '@briefed/ui';

import { AppVersion } from '../components/AppVersion';
import { DemoModeProvider } from '../demo/DemoModeProvider';
import { demoQueryClient } from '../demo/demoQueryClient';
import { RouteBaseProvider } from '../routing/routeBase';

import { BottomTabBar } from './BottomTabBar';
import { Sidebar } from './Sidebar';

/**
 * Read-only shell for `/demo/*` routes.
 *
 * @returns The rendered demo shell with synthetic data providers.
 */
export function DemoShell(): JSX.Element {
  return (
    <QueryClientProvider client={demoQueryClient}>
      <RouteBaseProvider base="/demo">
        <DemoModeProvider>
          <div className="flex min-h-[100dvh] flex-col md:flex-row">
            <Sidebar showLogout={false} />
            <main className="flex min-w-0 flex-1 flex-col bg-bg-canvas pb-[76px] md:pb-0">
              <div className="mx-auto w-full max-w-[var(--container-wide)] px-4 py-8 md:px-8">
                <div className="mb-4 flex justify-end">
                  <Badge tone="accent">Demo data</Badge>
                </div>
                <Outlet />
              </div>
              <footer className="mx-auto w-full max-w-[var(--container-wide)] px-4 pb-6 text-right md:px-8">
                <AppVersion />
              </footer>
            </main>
            <BottomTabBar />
          </div>
        </DemoModeProvider>
      </RouteBaseProvider>
    </QueryClientProvider>
  );
}
