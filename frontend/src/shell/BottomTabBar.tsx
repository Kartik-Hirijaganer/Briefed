import { NavLink } from 'react-router-dom';

import { NAV_ITEMS } from './navItems';

/**
 * Mobile bottom-tab bar. Renders only the primary tabs flagged as `mobile`
 * and reserves the iOS safe-area inset (plan §10 mobile UX).
 *
 * @returns The rendered tab bar.
 */
export function BottomTabBar(): JSX.Element {
  const tabs = NAV_ITEMS.filter((item) => item.mobile);
  return (
    <nav
      aria-label="Primary mobile"
      className="fixed inset-x-0 bottom-0 z-30 border-t border-border bg-bg md:hidden"
      style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
    >
      <ul className="grid grid-cols-4 gap-0">
        {tabs.map((tab) => (
          <li key={tab.to}>
            <NavLink
              to={tab.to}
              end={tab.to === '/'}
              className={({ isActive }) =>
                `flex min-h-[56px] flex-col items-center justify-center gap-1 text-xs ${
                  isActive ? 'text-accent' : 'text-fg-muted'
                }`
              }
            >
              <span aria-hidden="true" className="text-lg">
                {tab.glyph}
              </span>
              <span>{tab.label}</span>
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}
