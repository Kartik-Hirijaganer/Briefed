import { NavLink, Outlet } from 'react-router-dom';

interface SettingsTab {
  readonly to: string;
  readonly label: string;
}

const TABS: readonly SettingsTab[] = [
  { to: '/settings/accounts', label: 'Accounts' },
  { to: '/settings/preferences', label: 'Preferences' },
  { to: '/settings/prompts', label: 'Prompts' },
  { to: '/settings/schedule', label: 'Schedule' },
];

/**
 * Shared shell for the `/settings/*` surfaces.
 *
 * @returns The rendered layout.
 */
export default function SettingsLayout(): JSX.Element {
  return (
    <section className="flex flex-col gap-6">
      <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
      <nav aria-label="Settings sections" className="flex flex-wrap gap-2 border-b border-border">
        {TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            className={({ isActive }) =>
              `px-3 py-2 text-sm font-medium transition-colors ${
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
