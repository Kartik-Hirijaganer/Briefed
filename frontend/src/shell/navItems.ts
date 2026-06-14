import { History, Home, MailX, Settings, type LucideIcon } from 'lucide-react';

/**
 * Route for a top-level navigation target.
 */
export interface NavItem {
  /** App-relative route path. */
  readonly to: string;
  /** Short human label shown in sidebar / tab bar. */
  readonly label: string;
  /** Lucide icon component, rendered monochrome (inherits `currentColor`). */
  readonly icon: LucideIcon;
  /** When true, the item is rendered in the mobile `<BottomTabBar>`. */
  readonly mobile?: boolean;
}

/**
 * Canonical list of primary navigation targets (plan §10 IA).
 */
export const NAV_ITEMS: readonly NavItem[] = Object.freeze([
  { to: '', label: 'Home', icon: Home, mobile: true },
  { to: 'unsubscribe', label: 'Unsubscribe', icon: MailX },
  { to: 'history', label: 'History', icon: History, mobile: true },
  { to: 'settings/accounts', label: 'Settings', icon: Settings, mobile: true },
]);
