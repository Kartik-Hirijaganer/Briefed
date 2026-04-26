/**
 * Route for a top-level navigation target.
 */
export interface NavItem {
  /** URL path prefix. */
  readonly to: string;
  /** Short human label shown in sidebar / tab bar. */
  readonly label: string;
  /** Emoji glyph used as the low-weight icon in lieu of an icon system. */
  readonly glyph: string;
  /** When true, the item is rendered in the mobile `<BottomTabBar>`. */
  readonly mobile?: boolean;
}

/**
 * Canonical list of primary navigation targets (plan §10 IA).
 */
export const NAV_ITEMS: readonly NavItem[] = Object.freeze([
  { to: '/', label: 'Home', glyph: '🏠', mobile: true },
  { to: '/must-read', label: 'Must read', glyph: '⭐', mobile: true },
  { to: '/jobs', label: 'Jobs', glyph: '💼', mobile: true },
  { to: '/news', label: 'News', glyph: '📰' },
  { to: '/unsubscribe', label: 'Unsubscribe', glyph: '🧹' },
  { to: '/history', label: 'History', glyph: '📜' },
  { to: '/settings/accounts', label: 'Settings', glyph: '⚙️', mobile: true },
]);
