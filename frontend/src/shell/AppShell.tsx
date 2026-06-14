import { Outlet } from 'react-router-dom';

import { AppVersion } from '../components/AppVersion';
import { OfflineBanners } from '../features/offline/OfflineBanners';
import { QueuedActionsSheet } from '../features/offline/QueuedActionsSheet';
import { RouteBaseProvider } from '../routing/routeBase';

import { BottomTabBar } from './BottomTabBar';
import { Sidebar } from './Sidebar';

/**
 * Page-wrapping shell applied to every authenticated route. Renders the
 * sidebar on `≥ md` viewports, `<BottomTabBar>` on mobile. Content mounts
 * inside `<Outlet>`; individual routes own their own headings.
 *
 * @returns The rendered shell.
 */
export function AppShell(): JSX.Element {
  return (
    <RouteBaseProvider base="/app">
      <div className="flex min-h-[100dvh] flex-col md:flex-row">
        <Sidebar />
        <main className="flex min-w-0 flex-1 flex-col bg-bg-canvas pb-[76px] md:pb-0">
          <div className="mx-auto w-full max-w-[var(--container-wide)] px-4 py-8 md:px-8">
            <OfflineBanners />
            <Outlet />
          </div>
          <footer className="mx-auto w-full max-w-[var(--container-wide)] px-4 pb-6 text-right md:px-8">
            <AppVersion />
          </footer>
        </main>
        <QueuedActionsSheet />
        <BottomTabBar />
      </div>
    </RouteBaseProvider>
  );
}
