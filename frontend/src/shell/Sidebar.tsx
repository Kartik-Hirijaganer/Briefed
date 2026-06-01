import { NavLink } from 'react-router-dom';

import { NAV_ITEMS } from './navItems';

/**
 * Desktop left-hand sidebar for primary navigation.
 *
 * @returns The rendered sidebar element.
 */
export function Sidebar(): JSX.Element {
  return (
    <aside className="hidden md:flex md:w-60 md:shrink-0 md:flex-col md:border-r border-sidebar-border bg-sidebar">
      <div className="px-4 py-5 text-lg font-semibold tracking-tight text-sidebar-fg">Briefed</div>
      <nav aria-label="Primary" className="flex flex-1 flex-col gap-1 px-2">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/'}
            className={({ isActive }) =>
              `flex items-center gap-3 rounded-[var(--radius-md)] px-3 py-2 text-sm font-medium transition-colors ${
                isActive
                  ? 'bg-sidebar-active text-sidebar-fg'
                  : 'text-sidebar-fg-muted hover:bg-sidebar-hover'
              }`
            }
          >
            <item.icon aria-hidden="true" strokeWidth={1.75} className="h-4 w-4 shrink-0" />
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
