import { describe, expect, it } from 'vitest';

import { NAV_ITEMS } from '../shell/navItems';

describe('NAV_ITEMS', () => {
  it('exposes the seven primary routes', () => {
    expect(NAV_ITEMS.map((item) => item.to)).toEqual([
      '/',
      '/must-read',
      '/jobs',
      '/news',
      '/unsubscribe',
      '/history',
      '/settings/accounts',
    ]);
  });

  it('marks four entries as mobile tabs', () => {
    const mobile = NAV_ITEMS.filter((item) => item.mobile);
    expect(mobile).toHaveLength(4);
    expect(mobile.map((item) => item.to)).toEqual([
      '/',
      '/must-read',
      '/jobs',
      '/settings/accounts',
    ]);
  });

  it('every item has a non-empty label and glyph', () => {
    for (const item of NAV_ITEMS) {
      expect(item.label.length).toBeGreaterThan(0);
      expect(item.glyph.length).toBeGreaterThan(0);
    }
  });

  it('is frozen so consumers cannot mutate the canonical list', () => {
    expect(Object.isFrozen(NAV_ITEMS)).toBe(true);
  });
});
