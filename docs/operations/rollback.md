# Rollback rehearsal

Plan §14 Phase 9 + §20.6: rollback rehearsal is a release gate. This
page is the operator playbook *and* the rehearsal script we run before
every prod cut.

## Trust boundary

- A rollback is **one `aws lambda update-alias` per function** — api,
  worker, fanout. The `live` alias is the only thing serving traffic;
  pointing it back at the previous version is atomic.
- Forward-only Alembic + additive-first columns (plan §12) mean the
  *previous* Lambda version still serves correctly against the
  current schema. Rolling back the alias does **not** require rolling
  back the schema.
- Frontend rollback = re-deploying the previous PWA bundle to the
  same S3 bucket + CloudFront invalidation. Service workers will
  pick up the new manifest within their existing cache window.

## When to roll back

Roll back when **any** of the following fires within 30 minutes of an
alias swing:

1. `${name_prefix}-worker-init-errors` alarm — Lambda init failing on
   the new version (typical: SSM placeholder, KMS denial).
2. `${name_prefix}-digest-failure` alarm — pipeline completing with
   `failed` status more than once.
3. `${name_prefix}-dlq-depth` alarm — poison messages piling up after
   the deploy.
4. p95 user-visible 5xx > 2% on the CloudFront distribution.
5. Smoke test embedded in `deploy-prod.yml` failed (the workflow
   auto-rolled back; this entry is for the post-mortem).

If only the LLM-spend or Gmail-quota alarm fires, do *not* roll back
— neither is caused by the deploy. See
[`runbook.md`](runbook.md).

## Rollback steps (operator, ~3 minutes)

```sh
PREV_API_VER=$(aws lambda list-versions-by-function \
  --function-name briefed-prod-api \
  --query 'Versions[-2].Version' --output text)
PREV_WORKER_VER=$(aws lambda list-versions-by-function \
  --function-name briefed-prod-worker \
  --query 'Versions[-2].Version' --output text)
PREV_FANOUT_VER=$(aws lambda list-versions-by-function \
  --function-name briefed-prod-fanout \
  --query 'Versions[-2].Version' --output text)

aws lambda update-alias --function-name briefed-prod-api    \
  --name live --function-version "$PREV_API_VER"
aws lambda update-alias --function-name briefed-prod-worker \
  --name live --function-version "$PREV_WORKER_VER"
aws lambda update-alias --function-name briefed-prod-fanout \
  --name live --function-version "$PREV_FANOUT_VER"
```

Verify the alias swing landed:

```sh
curl --fail https://<cloudfront-domain>/health
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda --metric-name Errors \
  --dimensions Name=FunctionName,Value=briefed-prod-api \
  --statistics Sum --period 60 \
  --start-time "$(date -u -v-10M +%FT%TZ)" \
  --end-time   "$(date -u +%FT%TZ)"
```

Then write the audit row from the deploy host (the script tolerates a
duplicate `(version, git_sha)` and is safe to re-run):

```sh
PREV_VERSION=v<last-good-tag>
PREV_SHA=$(git rev-list -n 1 "$PREV_VERSION")
python backend/scripts/write_release_metadata.py \
  --version "$PREV_VERSION" --git-sha "$PREV_SHA" \
  --notes "rollback from v<bad-tag> at $(date -u +%FT%TZ)"
```

## Pre-cut verification

ADR 0016 removes the persistent dev stack. Before each production cut, use the
saved-plan and automated rollback controls instead of injecting a known-bad
image into a second environment. Wall-clock budget: 10 minutes.

1. Run `make ci` locally and require the GitHub CI workflow to be green.
2. Confirm each prod `live` alias targets a published version and that one prior
   version remains available:

   ```sh
   aws --profile personal-admin lambda get-alias \
     --function-name briefed-prod-api --name live
   aws --profile personal-admin lambda list-versions-by-function \
     --function-name briefed-prod-api
   # Repeat for worker and fanout.
   ```

3. Review the deploy workflow's saved Terraform plan. Its guard must report no
   KMS key, CloudFront distribution, Function URL, or WAF deletion/replacement.
4. Allow the workflow to apply only that plan. If the CloudFront smoke check
   fails, the workflow must move all three aliases back to the versions captured
   before apply.
5. Verify the workflow's runtime-wiring and no-drift checks, then confirm the
   new `release_metadata` row.

## Acceptance criteria for the rehearsal

The rehearsal **passes** when all of the following hold:

- Saved-plan protected-resource guard passes.
- All three aliases target numeric published versions and retain a prior version.
- CloudFront OpenAPI and body-bearing POST smoke checks pass.
- Six worker event-source mappings and the prod fanout schedule are enabled.
- The post-deploy Terraform plan is empty.
- New `release_metadata` row visible via
  `psql -c "SELECT version, git_sha, notes FROM release_metadata
  ORDER BY deployed_at DESC LIMIT 5;"`.
- The chaos test `backend/tests/chaos/test_dlq_drill.py` (existing
  Phase 8 drill) is green at the end.

## Frontend rollback (rare)

If only the PWA bundle is bad (Lambda is healthy but the dashboard
breaks), revert via:

```sh
PREV_TAG=v<last-good-tag>
git checkout "$PREV_TAG" -- frontend/
npm --workspace frontend ci
npm --workspace frontend run build
aws --profile personal-admin s3 sync frontend/dist "s3://briefed-prod-pwa" --delete
aws --profile personal-admin cloudfront create-invalidation \
  --distribution-id <dist-id> --paths "/*"
```

Service-worker users will pick up the previous manifest at their next
revalidation tick (default 24 h via Workbox; the `Scan Now` button
forces a refetch sooner).

## Cross-references

- Restore-from-backup drill: [`restore.md`](restore.md).
- Alarm catalog + thresholds: [`alarms.md`](alarms.md).
- Operator response per alarm: [`runbook.md`](runbook.md).
- Phase 9 release-metadata schema:
  [`backend/alembic/versions/0007_phase9_release_metadata.py`](../../backend/alembic/versions/0007_phase9_release_metadata.py).
