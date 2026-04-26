import type { components } from './schema';

type Components = components['schemas'];

/**
 * Stable frontend aliases over generated OpenAPI component names.
 *
 * The generated schema intentionally preserves backend DTO names like
 * `ConnectedAccountOut`; feature code uses this map so component imports stay
 * small while `schema.d.ts` remains fully generated.
 */
export interface Schemas {
  ConnectedAccount: Components['ConnectedAccountOut'];
  AccountsListResponse: Components['AccountsListResponse'];
  AccountPatchRequest: Components['ConnectedAccountPatchRequest'];
  UserPreferences: Components['UserPreferencesOut'];
  PreferencesPatchRequest: Components['PreferencesPatchRequest'];
  ManualRunRequest: Components['ManualRunRequest'];
  ManualRunResponse: Components['ManualRunResponse'];
  RunStatus: Components['RunStatusResponse'];
  EmailRow: Components['EmailRowOut'];
  EmailBucketPatchRequest: Components['EmailBucketPatchRequest'];
  EmailsListResponse: Components['EmailsListResponse'];
  JobMatch: Components['JobMatchOut'];
  JobsListResponse: Components['JobMatchesListResponse'];
  UnsubscribeSuggestion: Components['UnsubscribeSuggestionOut'];
  UnsubscribesListResponse: Components['UnsubscribeSuggestionsListResponse'];
  HygieneStats: Components['HygieneStatsResponse'];
  NewsCluster: Components['NewsCluster'];
  NewsDigestResponse: Components['NewsDigestResponse'];
  DigestToday: Components['DigestTodayResponse'];
  RubricRule: Components['RubricRuleOut'];
  RubricListResponse: Components['RubricRulesListResponse'];
  JobFilter: Components['JobFilterOut'];
  JobFiltersListResponse: Components['JobFiltersListResponse'];
  RunsListResponse: Components['RunsListResponse'];
}
