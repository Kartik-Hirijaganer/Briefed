import { Link, Outlet } from 'react-router-dom';

import { Button } from '@briefed/ui';

import { AppVersion } from '../components/AppVersion';
import { ConsentGate } from '../features/consent/ConsentGate';
import { OfflineBanners } from '../features/offline/OfflineBanners';
import { QueuedActionsSheet } from '../features/offline/QueuedActionsSheet';
import { useConsentGate, type ConsentGateState } from '../hooks/useConsentGate';
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
  const consent = useConsentGate();
  const consentOk = consent.status === 'ok';

  return (
    <RouteBaseProvider base="/app">
      <div className="flex min-h-[100dvh] flex-col md:flex-row">
        <Sidebar />
        <main className="flex min-w-0 flex-1 flex-col bg-bg-canvas pb-[76px] md:pb-0">
          <div className="mx-auto w-full max-w-[var(--container-wide)] px-4 py-8 md:px-8">
            {consentOk ? <OfflineBanners /> : null}
            {renderAppShellContent(consent)}
          </div>
          <footer className="mx-auto flex w-full max-w-[var(--container-wide)] flex-col gap-3 px-4 pb-6 text-sm text-fg-muted md:flex-row md:items-center md:justify-between md:px-8">
            <nav aria-label="Legal links" className="flex flex-wrap gap-3">
              <Link className="text-link underline-offset-4 hover:underline" to="/privacy">
                Privacy
              </Link>
              <Link className="text-link underline-offset-4 hover:underline" to="/terms">
                Terms
              </Link>
              <Link className="text-link underline-offset-4 hover:underline" to="/about">
                About
              </Link>
            </nav>
            <AppVersion />
          </footer>
        </main>
        {consentOk ? <QueuedActionsSheet /> : null}
        <BottomTabBar />
      </div>
    </RouteBaseProvider>
  );
}

function renderAppShellContent(consent: ConsentGateState): JSX.Element {
  switch (consent.status) {
    case 'loading':
      return <div aria-live="polite" className="min-h-[50vh]" />;
    case 'required':
      return <ConsentGate consent={consent.consent} />;
    case 'error':
      return (
        <div
          role="alert"
          className="rounded-[var(--radius-md)] border border-danger/40 bg-danger/5 p-4 text-sm text-fg"
        >
          <p className="font-semibold text-danger">Could not verify legal consent.</p>
          <p className="mt-1 text-fg-muted">{consent.error.message}</p>
          <Button
            variant="secondary"
            size="md"
            className="mt-3"
            onClick={() => void consent.retry()}
          >
            Retry
          </Button>
        </div>
      );
    case 'ok':
      return <Outlet />;
  }
}
