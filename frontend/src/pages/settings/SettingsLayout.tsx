import { LogOut } from 'lucide-react';
import { useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';

import { Button } from '@briefed/ui';

import { logoutAndClearBrowserSession } from '../../api/session';
import { useDemoMode } from '../../demo/DemoModeProvider';
import { useAppPath } from '../../routing/routeBase';

interface SettingsTab {
  readonly to: string;
  readonly label: string;
}

const TABS: readonly SettingsTab[] = [
  { to: 'settings/accounts', label: 'Accounts' },
  { to: 'settings/schedule', label: 'Schedule' },
  { to: 'settings/rules', label: 'Rules' },
  { to: 'settings/preferences', label: 'Preferences' },
];

/**
 * Shared shell for the `/settings/*` surfaces.
 *
 * @returns The rendered layout.
 */
export default function SettingsLayout(): JSX.Element {
  const { isDemo } = useDemoMode();
  const appPath = useAppPath();
  const [logoutPending, setLogoutPending] = useState<boolean>(false);
  const [logoutError, setLogoutError] = useState<string | null>(null);

  const handleLogout = async (): Promise<void> => {
    setLogoutPending(true);
    setLogoutError(null);
    try {
      await logoutAndClearBrowserSession();
    } catch {
      setLogoutError('Logout failed. Try again.');
      setLogoutPending(false);
    }
  };

  return (
    <section className="mx-auto flex w-full max-w-[var(--container-settings)] flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <h1 className="font-display text-2xl font-semibold tracking-tight">Settings</h1>
        {isDemo ? null : (
          <div className="flex flex-col items-end gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={handleLogout}
              loading={logoutPending}
              aria-label="Logout"
            >
              <LogOut aria-hidden="true" strokeWidth={1.75} className="h-4 w-4" />
              Logout
            </Button>
            {logoutError ? (
              <p role="alert" className="text-xs text-fg-muted">
                {logoutError}
              </p>
            ) : null}
          </div>
        )}
      </div>
      <nav aria-label="Settings sections" className="flex flex-wrap gap-2 border-b border-border">
        {TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={appPath(tab.to)}
            className={({ isActive }) =>
              `px-3 py-2 text-sm font-medium transition-[color,border-color] duration-[var(--motion-fast)] ease-[var(--ease-standard)] ${
                isActive ? 'border-b-2 border-accent text-accent' : 'text-fg-muted hover:text-fg'
              }`
            }
          >
            {tab.label}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </section>
  );
}
