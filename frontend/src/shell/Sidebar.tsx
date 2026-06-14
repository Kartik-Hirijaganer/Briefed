import { Spinner } from '@briefed/ui';
import { LogOut } from 'lucide-react';
import { useState } from 'react';
import { Link, NavLink } from 'react-router-dom';

import { logoutAndClearBrowserSession } from '../api/session';
import { BriefedMark } from '../components/brand/BriefedLogo';
import { useAppPath } from '../routing/routeBase';
import { NAV_ITEMS } from './navItems';

const ITEM_CLASS =
  'flex h-10 w-10 items-center justify-center rounded-[var(--radius-md)] ' +
  'duration-[var(--motion-fast)] ease-[var(--ease-standard)]';

/**
 * Props for {@link Sidebar}.
 */
export interface SidebarProps {
  /** Whether to render the logout control. */
  readonly showLogout?: boolean;
}

/**
 * Desktop left-hand navigation as a narrow icon rail. Every item is
 * icon-only with an `aria-label` + native `title` tooltip so the rail stays
 * accessible without visible labels. There is no theme toggle — the app ships
 * a single fixed Notion theme.
 *
 * @param props - Component props.
 * @returns The rendered sidebar element.
 */
export function Sidebar(props: SidebarProps = {}): JSX.Element {
  const { showLogout = true } = props;
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
    <aside className="hidden border-r border-sidebar-border bg-sidebar md:flex md:w-16 md:shrink-0 md:flex-col md:items-center">
      <Link
        to={appPath('')}
        aria-label="Briefed"
        title="Briefed"
        className="flex h-14 w-full items-center justify-center text-[var(--sidebar-accent)]"
      >
        <BriefedMark size={24} />
      </Link>
      <nav aria-label="Primary" className="flex flex-1 flex-col items-center gap-1 py-2">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.label}
            to={appPath(item.to)}
            end={item.to === ''}
            aria-label={item.label}
            title={item.label}
            className={({ isActive }) =>
              `${ITEM_CLASS} ${
                isActive
                  ? 'bg-sidebar-active text-sidebar-fg'
                  : 'text-sidebar-fg-muted hover:bg-sidebar-hover'
              }`
            }
          >
            <item.icon aria-hidden="true" strokeWidth={1.75} className="h-5 w-5" />
          </NavLink>
        ))}
      </nav>
      {showLogout ? (
        <div className="w-full border-t border-sidebar-border py-2">
          <div className="flex justify-center">
            <button
              type="button"
              onClick={handleLogout}
              disabled={logoutPending}
              aria-label="Logout"
              title="Logout"
              className={`${ITEM_CLASS} text-sidebar-fg-muted hover:bg-sidebar-hover hover:text-sidebar-fg disabled:cursor-not-allowed disabled:opacity-60`}
            >
              {logoutPending ? (
                <Spinner size="sm" />
              ) : (
                <LogOut aria-hidden="true" strokeWidth={1.75} className="h-5 w-5" />
              )}
            </button>
          </div>
          {logoutError ? (
            <p role="alert" className="sr-only">
              {logoutError}
            </p>
          ) : null}
        </div>
      ) : null}
    </aside>
  );
}
