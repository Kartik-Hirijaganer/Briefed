# Dev environment retirement and recovery

This runbook records the one-time retirement of the Briefed AWS dev stack. It
also defines the 30-day recovery path. FraudLens resources are outside this
runbook and must never be selected by any command.

## Safety invariants

- Use only an explicit AWS profile whose STS account is `970385384114`:

  ```bash
  aws --profile personal-admin sts get-caller-identity --query Account --output text
  ```

- Use the `dev/terraform.tfstate` object in
  `briefed-tf-state-dev-970385384114`; never infer a state from resource names.
- Save every Terraform plan and apply that exact plan file.
- Archive application data before emptying buckets or running destroy.
- Do not print SSM values, database URLs, OAuth credentials, or Terraform state.

## Archive layout

The 2026-08-12 archive lives at this versioned, SSE-KMS prefix:

```text
s3://briefed-prod-backups/retired-dev/2026-08-12T194900Z/
├── database/dev.dump
├── checksums/SHA256SUMS
├── inventory/
├── state/dev-terraform-redacted.tfstate
├── state/dev-terraform-final-redacted.tfstate
├── state/prod-terraform-redacted.tfstate
├── manifest.json
└── RESTORE.md
```

The custom-format PostgreSQL 17 dump was taken from the dev database before
retirement. A local restore completed with `--exit-on-error` after excluding
only the Supabase-managed `supabase_vault` extension objects unavailable in the
vanilla PostgreSQL validation image; the remaining 55 tables were counted.
Terraform snapshots redact every SSM parameter value. The dump, inventories,
states, checksums, and restore instructions are encrypted at rest with SSE-KMS;
no application secret value is stored in the archive.

The prod backup bucket expires `retired-dev/` objects and noncurrent versions
after 30 days. Every upload uses
`--sse aws:kms --sse-kms-key-id alias/briefed-prod-content-encrypt`.

## Retirement sequence

1. Pull dev and prod states, record their S3 version IDs, and run refresh-only
   plans using the currently deployed Lambda image URIs.
2. Set `fanout_schedule_enabled=false`, wait for every dev queue to reach zero,
   then set `worker_consumers_enabled=false` and
   `api_reserved_concurrency=0` through the dev Terraform state.
3. Read `/briefed/dev/supabase_db_url` without displaying it, create a
   custom-format `pg_dump`, and restore-test it in disposable PostgreSQL 17.
4. Upload the database dump, redacted state snapshots, inventories, counts, and
   checksums with SSE-KMS. The three dev business-data buckets were empty; the
   20-object rebuildable PWA bundle was inventoried but not archived.
5. Empty the four explicitly named dev buckets, including noncurrent versions
   and delete markers. Do not use bucket globs.
6. Create `terraform plan -destroy -out=destroy.tfplan`. Compare every planned
   address to `terraform state list`, review the summary, and apply only the
   saved plan.
7. Verify dev state is empty and delete the `briefed-tf-state-dev`
   CloudFormation stack. Its retained state bucket and lock table are then
   deleted explicitly after the pre-destroy state is archived.
8. Verify no `briefed-dev` Lambda, queue, WAF, CloudFront distribution, SSM
   parameter, alarm, or bucket remains. Dev KMS keys may remain only in
   `PendingDeletion` for the configured 30-day window.

## Restore during the recovery window

1. Cancel deletion of both former dev KMS keys before attempting to decrypt
   dev application-layer ciphertext in the restored database.
2. Download the archive with an explicit canonical-account profile and verify
   the SHA-256 values recorded in `checksums/SHA256SUMS`.
3. Restore `database/dev.dump` into a new isolated PostgreSQL 17 database.
   Install the Supabase extensions used by the source database or use the
   recorded validation list when validating without `supabase_vault`. Never
   overwrite prod directly.
4. Recreate infrastructure from a reviewed, temporary Terraform root only if
   database-level inspection is insufficient.
5. Reconcile selected records into prod through an audited migration. Do not
   repoint the live application at the restored database.

After either the archive lifecycle or KMS pending-deletion window expires,
recovery is not guaranteed.
