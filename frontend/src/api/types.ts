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
  UserProfile: Components['UserProfileOut'];
  UserProfilePatchRequest: Components['UserProfilePatchRequest'];
  UserPreferences: Components['UserPreferencesOut'];
  PreferencesPatchRequest: Components['PreferencesPatchRequest'];
  UserSchedule: Components['UserScheduleOut'];
  UserSchedulePatchRequest: Components['UserSchedulePatchRequest'];
  ManualRunRequest: Components['ManualRunRequest'];
  ManualRunResponse: Components['ManualRunResponse'];
  RunStatus: Components['RunStatusResponse'];
  EmailRow: Components['EmailRowOut'];
  EmailBucketPatchRequest: Components['EmailBucketPatchRequest'];
  EmailsListResponse: Components['EmailsListResponse'];
  ErrorEnvelope: Components['ErrorEnvelope'];
  MarkReadResponse: Components['MarkReadResponse'];
  UnsubscribeSuggestion: Components['UnsubscribeSuggestionOut'];
  UnsubscribesListResponse: Components['UnsubscribeSuggestionsListResponse'];
  UnsubscribeExecuteResponse: Components['UnsubscribeExecuteResponse'];
  ClientConfig: Components['ClientConfigResponse'];
  HygieneStats: Components['HygieneStatsResponse'];
  NewsCluster: Components['NewsCluster'];
  NewsDigestResponse: Components['NewsDigestResponse'];
  DigestToday: Components['DigestTodayResponse'];
  RubricRule: Components['RubricRuleOut'];
  RubricRuleInput: Components['RubricRuleIn'];
  RubricListResponse: Components['RubricRulesListResponse'];
  RunsListResponse: Components['RunsListResponse'];
  LegalConsentRequest: Components['LegalConsentRequest'];
  LegalConsentStatus: Components['LegalConsentStatusOut'];
}
