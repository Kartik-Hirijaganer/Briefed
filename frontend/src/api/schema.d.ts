/**
 * Generated-shape stub for the Briefed OpenAPI spec.
 *
 * The real file is produced by `npm run codegen` (openapi-typescript against
 * packages/contracts/openapi.json). This committed stub covers only the
 * operations the frontend currently consumes so tsc can resolve imports
 * before the first codegen run; `make docs && npm run codegen` regenerates
 * it for the full surface. CI enforces drift.
 */

/** Minimal OpenAPI `paths` shape keyed by route template. */
export interface paths {
  '/api/v1/accounts': {
    get: operations['list_accounts'];
  };
  '/api/v1/accounts/{account_id}': {
    delete: operations['disconnect_account'];
    patch: operations['patch_account'];
  };
  '/api/v1/preferences': {
    get: operations['get_preferences'];
    patch: operations['patch_preferences'];
  };
  '/api/v1/runs': {
    post: operations['start_manual_run'];
  };
  '/api/v1/runs/{run_id}': {
    get: operations['get_run'];
  };
  '/api/v1/runs/{run_id}/events': {
    get: operations['stream_run_events'];
  };
  '/api/v1/jobs': {
    get: operations['list_jobs'];
  };
  '/api/v1/unsubscribes': {
    get: operations['list_unsubscribes'];
  };
  '/api/v1/unsubscribes/{suggestion_id}/confirm': {
    post: operations['confirm_unsubscribe'];
  };
  '/api/v1/unsubscribes/{suggestion_id}/dismiss': {
    post: operations['dismiss_unsubscribe'];
  };
  '/api/v1/hygiene/stats': {
    get: operations['hygiene_stats'];
  };
  '/api/v1/rubric': {
    get: operations['list_rubric_rules'];
  };
  '/api/v1/job-filters': {
    get: operations['list_job_filters'];
  };
  '/api/v1/digest/today': {
    get: operations['digest_today'];
  };
  '/api/v1/emails': {
    get: operations['list_emails'];
  };
  '/api/v1/news': {
    get: operations['news_digest'];
  };
  '/api/v1/history': {
    get: operations['list_runs'];
  };
}

export type components = { schemas: Schemas };

/** Cross-view shared schemas. */
export interface Schemas {
  ConnectedAccount: {
    id: string;
    email: string;
    display_name?: string | null;
    provider: 'gmail' | 'outlook' | 'imap';
    status: 'active' | 'paused' | 'needs_reauth' | 'error';
    auto_scan_enabled: boolean | null;
    exclude_from_global_digest: boolean;
    created_at: string;
    last_sync_at?: string | null;
    emails_ingested_24h: number;
    daily_budget_used_pct: number;
  };
  AccountsListResponse: {
    accounts: Schemas['ConnectedAccount'][];
  };
  AccountPatchRequest: {
    auto_scan_enabled?: boolean | null;
    exclude_from_global_digest?: boolean;
    display_name?: string;
  };
  UserPreferences: {
    auto_execution_enabled: boolean;
    digest_send_hour_utc: number;
    redact_pii: boolean;
    secure_offline_mode: boolean;
    retention_policy_json: Record<string, unknown>;
  };
  PreferencesPatchRequest: Partial<Schemas['UserPreferences']>;
  ManualRunRequest: {
    kind: 'manual';
    account_ids?: string[];
  };
  ManualRunResponse: {
    run_id: string;
    accounts_queued: number;
  };
  RunStatus: {
    id: string;
    status: 'queued' | 'running' | 'complete' | 'failed';
    trigger_type: 'scheduled' | 'manual';
    started_at: string;
    completed_at?: string | null;
    stats: {
      ingested: number;
      classified: number;
      summarized: number;
      new_must_read: number;
    };
    cost_cents?: number;
    error?: string | null;
  };
  EmailRow: {
    id: string;
    account_email: string;
    thread_id: string;
    subject: string;
    sender: string;
    received_at: string;
    bucket: 'must_read' | 'good_to_read' | 'ignore' | 'waste';
    confidence: number;
    decision_source: 'rule' | 'llm' | 'hybrid';
    reasons: string[];
    summary_excerpt?: string | null;
  };
  EmailsListResponse: {
    emails: Schemas['EmailRow'][];
    total: number;
  };
  JobMatch: {
    id: string;
    title: string;
    company: string;
    location?: string | null;
    salary_range?: string | null;
    url?: string | null;
    source_email_id: string;
    match_reason: string;
    passed_filter: boolean;
    confidence: number;
  };
  JobsListResponse: {
    jobs: Schemas['JobMatch'][];
  };
  UnsubscribeSuggestion: {
    id: string;
    sender_domain: string;
    sender_name: string;
    score: number;
    received_count_30d: number;
    last_opened_at?: string | null;
    unsubscribe_url?: string | null;
    reason_summary: string;
    status: 'pending' | 'dismissed' | 'confirmed';
  };
  UnsubscribesListResponse: {
    suggestions: Schemas['UnsubscribeSuggestion'][];
  };
  HygieneStats: {
    days_ingested: number;
    emails_ingested: number;
    must_read_ratio: number;
    waste_ratio: number;
    top_waste_domains: { domain: string; count: number }[];
  };
  NewsCluster: {
    id: string;
    label: string;
    summary_md: string;
    email_ids: string[];
  };
  NewsDigestResponse: {
    generated_at: string;
    clusters: Schemas['NewsCluster'][];
  };
  DigestToday: {
    generated_at: string | null;
    cost_cents_today: number;
    counts: { must_read: number; good_to_read: number; ignore: number; waste: number };
    must_read_preview: Schemas['EmailRow'][];
    last_successful_run_at?: string | null;
  };
  RubricRule: {
    id: string;
    label: string;
    priority: number;
    predicate_json: Record<string, unknown>;
    bucket: 'must_read' | 'good_to_read' | 'ignore' | 'waste';
  };
  RubricListResponse: {
    rules: Schemas['RubricRule'][];
  };
  JobFilter: {
    id: string;
    label: string;
    predicate_json: Record<string, unknown>;
    enabled: boolean;
  };
  JobFiltersListResponse: {
    filters: Schemas['JobFilter'][];
  };
  RunsListResponse: {
    runs: Schemas['RunStatus'][];
  };
}

/** Compact operation shapes used by openapi-fetch. */
export interface operations {
  list_accounts: {
    responses: { 200: { content: { 'application/json': Schemas['AccountsListResponse'] } } };
  };
  disconnect_account: {
    parameters: { path: { account_id: string } };
    responses: { 204: { content: Record<string, never> } };
  };
  patch_account: {
    parameters: { path: { account_id: string } };
    requestBody: { content: { 'application/json': Schemas['AccountPatchRequest'] } };
    responses: { 200: { content: { 'application/json': Schemas['ConnectedAccount'] } } };
  };
  get_preferences: {
    responses: { 200: { content: { 'application/json': Schemas['UserPreferences'] } } };
  };
  patch_preferences: {
    requestBody: { content: { 'application/json': Schemas['PreferencesPatchRequest'] } };
    responses: { 200: { content: { 'application/json': Schemas['UserPreferences'] } } };
  };
  start_manual_run: {
    requestBody: { content: { 'application/json': Schemas['ManualRunRequest'] } };
    responses: { 202: { content: { 'application/json': Schemas['ManualRunResponse'] } } };
  };
  get_run: {
    parameters: { path: { run_id: string } };
    responses: { 200: { content: { 'application/json': Schemas['RunStatus'] } } };
  };
  stream_run_events: {
    parameters: { path: { run_id: string } };
    responses: { 200: { content: { 'text/event-stream': string } } };
  };
  list_jobs: {
    parameters: { query?: { passed_filter?: boolean } };
    responses: { 200: { content: { 'application/json': Schemas['JobsListResponse'] } } };
  };
  list_unsubscribes: {
    responses: { 200: { content: { 'application/json': Schemas['UnsubscribesListResponse'] } } };
  };
  confirm_unsubscribe: {
    parameters: { path: { suggestion_id: string } };
    responses: { 204: { content: Record<string, never> } };
  };
  dismiss_unsubscribe: {
    parameters: { path: { suggestion_id: string } };
    responses: { 204: { content: Record<string, never> } };
  };
  hygiene_stats: {
    responses: { 200: { content: { 'application/json': Schemas['HygieneStats'] } } };
  };
  list_rubric_rules: {
    responses: { 200: { content: { 'application/json': Schemas['RubricListResponse'] } } };
  };
  list_job_filters: {
    responses: { 200: { content: { 'application/json': Schemas['JobFiltersListResponse'] } } };
  };
  digest_today: {
    responses: { 200: { content: { 'application/json': Schemas['DigestToday'] } } };
  };
  list_emails: {
    parameters: {
      query?: {
        bucket?: 'must_read' | 'good_to_read' | 'ignore' | 'waste';
        account_id?: string;
        limit?: number;
      };
    };
    responses: { 200: { content: { 'application/json': Schemas['EmailsListResponse'] } } };
  };
  news_digest: {
    responses: { 200: { content: { 'application/json': Schemas['NewsDigestResponse'] } } };
  };
  list_runs: {
    responses: { 200: { content: { 'application/json': Schemas['RunsListResponse'] } } };
  };
}
