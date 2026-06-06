import { describe, expect, it } from 'vitest';

import type { Schemas } from '../api/types';
import {
  flaggedCount,
  openedPercent,
  preferredUnsubscribeUrl,
  senderTags,
  wastedEmailsPerMonth,
} from '../features/unsubscribe/unsubscribeDerived';

type Suggestion = Schemas['UnsubscribeSuggestion'];

const make = (overrides: Partial<Suggestion> = {}): Suggestion => ({
  id: 's1',
  sender_domain: 'news.example',
  sender_email: 'noisy@news.example',
  frequency_30d: 30,
  engagement_score: '0.05',
  waste_rate: '0.80',
  confidence: '0.90',
  decision_source: 'rule',
  category: null,
  rationale: 'opened 0/30',
  list_unsubscribe: { http_urls: ['https://news.example/unsub'], mailto: null, one_click: true },
  dismissed: false,
  dismissed_at: null,
  last_email_at: null,
  created_at: '2026-06-01T00:00:00Z',
  updated_at: '2026-06-01T00:00:00Z',
  recent_subjects: ['Deal A', 'Deal B'],
  ...overrides,
});

describe('unsubscribeDerived', () => {
  it('flaggedCount counts what is shown', () => {
    expect(flaggedCount([make(), make({ id: 's2' })])).toBe(2);
    expect(flaggedCount([])).toBe(0);
  });

  it('wastedEmailsPerMonth sums freq × waste and rounds', () => {
    // 30 * 0.80 = 24 ; 10 * 0.50 = 5 → 29
    const result = wastedEmailsPerMonth([
      make({ frequency_30d: 30, waste_rate: '0.80' }),
      make({ id: 's2', frequency_30d: 10, waste_rate: '0.50' }),
    ]);
    expect(result).toBe(29);
  });

  it('wastedEmailsPerMonth drops non-finite terms (NaN guard)', () => {
    const result = wastedEmailsPerMonth([
      make({ frequency_30d: 30, waste_rate: '0.80' }), // 24
      make({ id: 's2', frequency_30d: 10, waste_rate: 'not-a-number' }), // NaN → dropped
    ]);
    expect(result).toBe(24);
  });

  it('openedPercent rounds engagement × 100 and guards NaN', () => {
    expect(openedPercent(make({ engagement_score: '0.05' }))).toBe(5);
    expect(openedPercent(make({ engagement_score: '0.126' }))).toBe(13);
    expect(openedPercent(make({ engagement_score: 'bad' }))).toBe(0);
  });

  it('senderTags applies thresholds at the boundary', () => {
    // noisy at >= 20, disengaged at <= 0.10, low_value at >= 0.70
    expect(
      senderTags(make({ frequency_30d: 20, engagement_score: '0.10', waste_rate: '0.70' })),
    ).toEqual(['noisy', 'disengaged', 'low_value']);
    // Just under every boundary → no tags.
    expect(
      senderTags(make({ frequency_30d: 19, engagement_score: '0.11', waste_rate: '0.69' })),
    ).toEqual([]);
  });

  it('preferredUnsubscribeUrl prefers https, then http, then mailto, else null', () => {
    expect(
      preferredUnsubscribeUrl(
        make({
          list_unsubscribe: {
            http_urls: ['http://x.example/u', 'https://y.example/u'],
            mailto: 'mailto:z@x',
            one_click: false,
          },
        }),
      ),
    ).toBe('https://y.example/u');
    expect(
      preferredUnsubscribeUrl(
        make({
          list_unsubscribe: { http_urls: ['http://x.example/u'], mailto: null, one_click: false },
        }),
      ),
    ).toBe('http://x.example/u');
    expect(
      preferredUnsubscribeUrl(
        make({
          list_unsubscribe: { http_urls: [], mailto: 'mailto:z@x', one_click: false },
        }),
      ),
    ).toBe('mailto:z@x');
    expect(preferredUnsubscribeUrl(make({ list_unsubscribe: null }))).toBeNull();
  });
});
