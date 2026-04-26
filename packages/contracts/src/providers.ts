/**
 * Provider seams shared between backend and frontend types.
 *
 * These mirror the Python `Protocol` classes in `backend/app/domain/` and
 * `backend/app/llm/`. They exist so that frontend code (e.g. account UI
 * that talks to different mailbox providers) can consume the same vocabulary
 * without a backend round-trip.
 */

/**
 * Identifier for a single message inside a mailbox provider.
 */
export type MessageId = string;

/**
 * Opaque sync cursor passed back to the provider on each incremental fetch.
 */
export interface SyncCursor {
  readonly providerId: string;
  readonly accountId: string;
  readonly value: string;
}

/**
 * Minimum surface a mailbox provider exposes to the ingestion pipeline.
 * Backend implementations: `GmailProvider` (1.0.0), future `OutlookProvider`.
 */
export interface MailboxProvider {
  readonly kind: 'gmail' | 'outlook' | 'imap';
}

/**
 * Identity of an LLM provider adapter. Backend implementations:
 * `GeminiProvider` (primary), `AnthropicDirectProvider` (gated fallback).
 */
export interface LLMProviderDescriptor {
  readonly name: 'gemini' | 'anthropic_direct' | 'bedrock' | 'openrouter';
  readonly model: string;
}

/**
 * Authentication backend. Release 1.0.0 ships only `local`; `cognito` is an
 * additive seam for hosted deployments (plan §20.1).
 */
export type AuthProviderKind = 'local' | 'cognito';
