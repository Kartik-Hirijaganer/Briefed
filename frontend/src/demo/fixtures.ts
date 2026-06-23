import type { QueryClient } from '@tanstack/react-query';

import {
  accounts,
  clientConfig,
  digestToday,
  emails,
  history,
  preferences,
  rubric,
  run,
  schedule,
  unsubscribes,
  type EmailsQueryParams,
} from '../api/queryKeys';
import type { Schemas } from '../api/types';

const DEMO_ACCOUNT_ID = '00000000-0000-4000-8000-0000000000a1';
const DEMO_USER_EMAIL = 'demo@briefeddemo.com';

/**
 * Stable demo run id linked from the demo history page.
 */
export const DEMO_RUN_ID = '00000000-0000-4000-8000-000000000100';

const demoNow = new Date();

const hoursAgo = (hours: number): string =>
  new Date(demoNow.getTime() - hours * 60 * 60 * 1000).toISOString();

const daysAgo = (days: number): string =>
  new Date(demoNow.getTime() - days * 24 * 60 * 60 * 1000).toISOString();

const email = (
  index: number,
  payload: Omit<Schemas['EmailRow'], 'id' | 'account_email' | 'thread_id' | 'received_at'>,
): Schemas['EmailRow'] => ({
  id: `00000000-0000-4000-8000-00000000000${index}`,
  account_email: DEMO_USER_EMAIL,
  thread_id: `demo-thread-${index}`,
  received_at: hoursAgo(index + 1),
  ...payload,
});

const demoEmails: readonly Schemas['EmailRow'][] = Object.freeze([
  email(1, {
    subject: 'Q3 board deck - your section needs a final pass',
    sender: 'Dana Cole <ceo@bigco.example>',
    bucket: 'must_read',
    confidence: 0.94,
    needs_review: false,
    decision_source: 'rule',
    reasons: ['Sender is on your VIP rules.', 'Mentions a deadline this week.'],
    summary_excerpt:
      "**TL;DR** Dana needs your revenue slides finalized before Thursday's board review.",
  }),
  email(2, {
    subject: 'Your flight BA242 is delayed',
    sender: 'British Airways <noreply@ba.example>',
    bucket: 'must_read',
    confidence: 0.61,
    needs_review: true,
    decision_source: 'hybrid',
    reasons: ['Time-sensitive travel update.', 'Low confidence - double-check the new gate.'],
    summary_excerpt: '**TL;DR** BA242 now departs 21:40 from gate B32.',
  }),
  email(3, {
    subject: "Today's top 5 launches",
    sender: 'Product Hunt <news@producthunt.example>',
    bucket: 'good_to_read',
    confidence: 0.78,
    needs_review: false,
    decision_source: 'llm',
    reasons: ['Newsletter you open most weeks.'],
    summary_excerpt: "**TL;DR** An AI meeting-notes tool and a Postgres GUI top today's list.",
  }),
  email(4, {
    subject: 'Your invoice for May is ready',
    sender: 'Stripe <billing@stripe.example>',
    bucket: 'good_to_read',
    confidence: 0.82,
    needs_review: false,
    decision_source: 'rule',
    reasons: ['Billing from a service you use.'],
    summary_excerpt: null,
  }),
  email(5, {
    subject: '50% OFF everything - today only!',
    sender: 'MegaDeals <deals@promo.example>',
    bucket: 'ignore',
    confidence: 0.97,
    needs_review: false,
    decision_source: 'rule',
    reasons: ['High-volume promotional sender.', 'You never open these.'],
    summary_excerpt: null,
  }),
]);

const demoRunCompletedAt = hoursAgo(0.92);

const demoRun: Schemas['RunStatus'] = {
  id: DEMO_RUN_ID,
  status: 'complete',
  trigger_type: 'scheduled',
  started_at: hoursAgo(1),
  completed_at: demoRunCompletedAt,
  stats: { ingested: 5, classified: 5, summarized: 3, new_must_read: 2 },
  cost_cents: 12,
  error: null,
};

const demoUnsubscribes: readonly Schemas['UnsubscribeSuggestion'][] = Object.freeze([
  {
    id: '00000000-0000-4000-8000-000000000201',
    sender_domain: 'promo.example',
    sender_email: 'deals@promo.example',
    frequency_30d: 42,
    engagement_score: '0.020',
    waste_rate: '0.880',
    confidence: '0.920',
    decision_source: 'rule',
    category: null,
    rationale: '42 emails in 30 days, 2% opened, 88% wasted - all criteria triggered.',
    list_unsubscribe: {
      http_urls: ['https://httpbin.org/status/200'],
      mailto: null,
      one_click: true,
    },
    dismissed: false,
    dismissed_at: null,
    last_email_at: hoursAgo(3),
    created_at: daysAgo(14),
    updated_at: hoursAgo(3),
    recent_subjects: ['50% OFF everything', 'Flash sale ends tonight', 'Last chance - 6 hrs left'],
  },
  {
    id: '00000000-0000-4000-8000-000000000202',
    sender_domain: 'medium.example',
    sender_email: 'newsletter@medium.example',
    frequency_30d: 18,
    engagement_score: '0.080',
    waste_rate: '0.560',
    confidence: '0.860',
    decision_source: 'model',
    category: 'newsletter',
    rationale: 'Daily digest you rarely open; HTTP-only unsubscribe opens for manual finish.',
    list_unsubscribe: {
      http_urls: ['http://medium.example/unsub/abc'],
      mailto: null,
      one_click: false,
    },
    dismissed: false,
    dismissed_at: null,
    last_email_at: hoursAgo(3),
    created_at: daysAgo(12),
    updated_at: hoursAgo(3),
    recent_subjects: ["Today's highlights", 'Recommended for you'],
  },
  {
    id: '00000000-0000-4000-8000-000000000203',
    sender_domain: 'social.example',
    sender_email: 'no-reply@social.example',
    frequency_30d: 60,
    engagement_score: '0.100',
    waste_rate: '0.410',
    confidence: '0.880',
    decision_source: 'rule',
    category: null,
    rationale: '60 notifications in 30 days; mailto-only unsubscribe.',
    list_unsubscribe: {
      http_urls: [],
      mailto: 'mailto:unsubscribe@social.example?subject=unsubscribe',
      one_click: false,
    },
    dismissed: false,
    dismissed_at: null,
    last_email_at: hoursAgo(3),
    created_at: daysAgo(10),
    updated_at: hoursAgo(3),
    recent_subjects: ['3 people liked your post', 'You have 5 new notifications'],
  },
  {
    id: '00000000-0000-4000-8000-000000000204',
    sender_domain: 'digest.example',
    sender_email: 'weekly@digest.example',
    frequency_30d: 25,
    engagement_score: '0.150',
    waste_rate: '0.720',
    confidence: '0.810',
    decision_source: 'model',
    category: 'newsletter',
    rationale: 'Noisy weekly digest with low engagement; supports one-click unsubscribe.',
    list_unsubscribe: {
      http_urls: ['https://httpbin.org/status/200'],
      mailto: null,
      one_click: true,
    },
    dismissed: false,
    dismissed_at: null,
    last_email_at: hoursAgo(3),
    created_at: daysAgo(8),
    updated_at: hoursAgo(3),
    recent_subjects: ['Your weekly roundup', 'This week in tech'],
  },
]);

/**
 * Complete synthetic response set used by `/demo`.
 */
export const DEMO_FIXTURES = Object.freeze({
  digestToday: {
    generated_at: demoRunCompletedAt,
    cost_cents_today: 12,
    counts: { must_read: 2, good_to_read: 2, ignore: 1 },
    rule_decided: 3,
    category_summaries: [
      {
        category: 'must_read',
        narrative: 'Board prep and travel updates need attention today.',
        groups: [
          {
            label: 'Time-sensitive',
            bullets: ['Finish the board deck section.', 'Check the delayed flight details.'],
            item_refs: ['demo-1', 'demo-2'],
          },
        ],
        confidence: 0.91,
      },
      {
        category: 'good_to_read',
        narrative: 'Useful product and billing updates can wait until later.',
        groups: [
          {
            label: 'Reference',
            bullets: ['Product Hunt has a few launches worth scanning.'],
            item_refs: ['demo-3'],
          },
        ],
        confidence: 0.84,
      },
    ],
    must_read_preview: demoEmails.filter((row) => row.bucket === 'must_read'),
    last_successful_run_at: demoRunCompletedAt,
  } satisfies Schemas['DigestToday'],
  clientConfig: { unsubscribe_execute: false } satisfies Schemas['ClientConfig'],
  accounts: {
    accounts: [
      {
        id: DEMO_ACCOUNT_ID,
        email: DEMO_USER_EMAIL,
        display_name: 'Demo Gmail',
        provider: 'gmail',
        status: 'active',
        auto_scan_enabled: true,
        exclude_from_global_digest: false,
        created_at: daysAgo(30),
        last_sync_at: demoRunCompletedAt,
        emails_ingested_24h: 5,
        daily_budget_used_pct: 8,
      },
    ],
  } satisfies Schemas['AccountsListResponse'],
  preferences: {
    auto_execution_enabled: true,
    digest_send_hour_utc: 13,
    redact_pii: false,
    secure_offline_mode: false,
    retention_policy_json: { email_body_days: 30, summary_days: 180 },
  } satisfies Schemas['UserPreferences'],
  schedule: {
    schedule_frequency: 'once_daily',
    schedule_times_local: ['08:00'],
    schedule_timezone: 'America/New_York',
    next_run_at_utc: hoursAgo(-19),
  } satisfies Schemas['UserSchedule'],
  rubric: {
    rules: [
      {
        id: '00000000-0000-4000-8000-000000000301',
        name: 'VIP senders',
        priority: 1000,
        match: { from_email: 'ceo@bigco.example' },
        action: { label: 'must_read', confidence: 0.95 },
        version: 1,
        active: true,
        created_at: daysAgo(28),
        updated_at: daysAgo(5),
      },
      {
        id: '00000000-0000-4000-8000-000000000302',
        name: 'Promo domains',
        priority: 200,
        match: { from_domain: 'promo.example' },
        action: { label: 'ignore', confidence: 0.9 },
        version: 1,
        active: true,
        created_at: daysAgo(21),
        updated_at: daysAgo(7),
      },
    ],
  } satisfies Schemas['RubricListResponse'],
  history: { runs: [demoRun] } satisfies Schemas['RunsListResponse'],
  run: demoRun,
  unsubscribes: {
    suggestions: [...demoUnsubscribes],
  } satisfies Schemas['UnsubscribesListResponse'],
});

/**
 * Seed the supplied QueryClient with every query key used by demo routes.
 *
 * @param client - Demo-scoped QueryClient.
 */
export function seedDemoCache(client: QueryClient): void {
  client.setQueryData(digestToday(), DEMO_FIXTURES.digestToday);
  client.setQueryData(unsubscribes(), DEMO_FIXTURES.unsubscribes);
  client.setQueryData(clientConfig(), DEMO_FIXTURES.clientConfig);
  client.setQueryData(history(), DEMO_FIXTURES.history);
  client.setQueryData(run(DEMO_RUN_ID), DEMO_FIXTURES.run);
  client.setQueryData(accounts(), DEMO_FIXTURES.accounts);
  client.setQueryData(preferences(), DEMO_FIXTURES.preferences);
  client.setQueryData(schedule(), DEMO_FIXTURES.schedule);
  client.setQueryData(rubric(), DEMO_FIXTURES.rubric);
  seedEmailVariants(client);
}

function seedEmailVariants(client: QueryClient): void {
  const variants: readonly EmailsQueryParams[] = [
    { offset: 0, limit: 25 },
    { bucket: 'must_read', offset: 0, limit: 25 },
    { bucket: 'good_to_read', offset: 0, limit: 25 },
    { bucket: 'ignore', offset: 0, limit: 25 },
  ];
  client.setQueryData(emails(), emailList({ offset: 0, limit: 25 }));
  for (const params of variants) {
    client.setQueryData(emails(params), emailList(params));
  }
}

function emailList(params: EmailsQueryParams): Schemas['EmailsListResponse'] {
  const filtered = params.bucket
    ? demoEmails.filter((row) => row.bucket === params.bucket)
    : demoEmails;
  return {
    emails: filtered.slice(params.offset, params.offset + params.limit),
    total: filtered.length,
  };
}
