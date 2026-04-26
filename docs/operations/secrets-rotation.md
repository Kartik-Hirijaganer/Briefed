# Secrets rotation

Quarterly rotation procedure for SSM `SecureString` parameters and the
two KMS CMKs. Plan §14 Phase 8 calls for a "secret-rotation dry run"
during hardening; this page documents both the dry run and the live
rotation.

## Cadence

- **SSM SecureString parameters** (`gemini_api_key`, `anthropic_api_key`,
  `session_signing_key`, `google_oauth_client_*`, `supabase_*`):
  rotate every 90 days or immediately on suspected leak.
- **KMS CMK rotation** (`alias/${env}-token-wrap`,
  `alias/${env}-content-encrypt`): annual, AWS-managed automatic
  rotation enabled (`enable_key_rotation = true`). No application change
  required — wrap-key material never leaves KMS.

## Dry run (chaos drill)

The chaos drill at
`backend/tests/chaos/test_secret_rotation_drill.py` exercises the
hydration path with a stubbed SSM client whose values rotate between
calls. CI runs this with `pytest -m chaos`. The drill catches:

- A new sync call landing in `Settings` init (would slow SnapStart).
- Forgetting to invalidate the `lru_cache` on `get_settings()` — the
  drill calls `load_settings` directly, but a regression in
  `get_settings` invalidation is caught by the integration test that
  follows.

## Live rotation

1. Generate the new value out-of-band (e.g. `openssl rand -hex 32` for
   `session_signing_key`, the provider's console for API keys).
2. `aws ssm put-parameter --name "/briefed/${env}/<short>" --type
   SecureString --value "$NEW" --overwrite`.
3. Trigger a fresh deploy. SnapStart will re-snapshot the warm process
   with the new value. The previous warm window keeps using the old
   value until it expires; for OAuth tokens this is fine because each
   token unwrap is independent.
4. Verify by tailing the worker log group for
   `event=settings.loaded` and confirming the SSM versions match.
5. Revoke the old value (provider console — not strictly required for
   SSM since it is overwritten, but required for API keys at the
   provider).

## Emergency rotation

If a key may be compromised:

1. Revoke the IAM grant for the affected role (`kms:Decrypt` for token
   reads, `kms:Decrypt` on the content CMK for summary reads). The
   chaos drill `test_kms_revocation_drill.py` proves the application
   surfaces a `CryptoError` rather than leaking plaintext.
2. Rotate the SSM parameter (steps above).
3. Restore the IAM grant and redeploy.
4. File a CloudTrail filter for any `Decrypt` calls outside the
   expected role; alert on the `${name_prefix}-kms-decrypt-anomaly`
   alarm continuing to fire.
