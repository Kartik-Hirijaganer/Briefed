# Restore drill

Plan §20.10 Phase 8 requires the restore-from-backup drill to verify
that `pg_dump` snapshots are useless without a `kms:Decrypt` grant on
the content CMK. This page is the operator playbook.

## Pre-flight

- Confirm the destination Supabase project is empty.
- Confirm the destination AWS account does *not* have a `kms:Decrypt`
  grant on the production content CMK yet.
- Run `make migrate` against the destination project to materialize
  the schema before importing data.

## Steps

1. **Pull the latest dump.**

   ```sh
   pg_dump --format=custom \
     --dbname "$BRIEFED_PROD_DATABASE_URL" \
     --file ./briefed-prod.dump
   ```

2. **Restore into the empty target project.**

   ```sh
   pg_restore --no-owner --dbname "$BRIEFED_TARGET_DATABASE_URL" \
     ./briefed-prod.dump
   ```

3. **Verify the data is unreadable without KMS.** Connect to the
   target project; `SELECT body_md_ct, body_dek_wrapped FROM
   summaries LIMIT 1;` should return opaque bytes. Calling the
   application API (`/api/v1/digest/today`) without the CMK grant
   produces a 5xx + `CryptoError` log line — *do not* surface the
   error message to the user; it confirms the boundary held.

4. **Grant `kms:Decrypt` on the content CMK to the target Lambda
   role** (e.g. via Terraform `iam_policy_attachment` for the
   restore-only role). Re-run the API call. The summary now decrypts
   to plaintext markdown.

5. **Tear down.** Revoke the grant and delete the temporary Supabase
   project. Do *not* leave a long-lived restore CMK grant in place —
   it widens the attack surface for the original threat model row 8.

## Drift checks

The chaos test
`backend/tests/chaos/test_kms_revocation_drill.py` exercises the same
boundary at unit level. The restore drill is the integration-level
proof; both should be green for Phase 8 sign-off.
