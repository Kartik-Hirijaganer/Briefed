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

## Rehearsal — run this before every prod cut

The rehearsal is run against the dev stack so prod is never touched.
Wall-clock budget: 10 minutes.

1. **Note the current dev `live` version.**

   ```sh
   aws lambda get-alias --function-name briefed-dev-api    --name live
   aws lambda get-alias --function-name briefed-dev-worker --name live
   aws lambda get-alias --function-name briefed-dev-fanout --name live
   ```

2. **Inject a known-bad image.** Build a debug image with `RAISE=1`
   in the api entrypoint (or pin a deliberately old image tag) and
   run the dev deploy workflow:

   ```sh
   gh workflow run deploy-dev.yml \
     --ref dev \
     --field image_tag=<known-bad-tag>
   ```

   The CloudWatch alarms `${name_prefix}-worker-init-errors` and
   `${name_prefix}-digest-failure` should trip within 5 minutes.

3. **Run the rollback steps above against `briefed-dev-*`.** Confirm
   `/health` returns 200 within 60 s of the alias swap. Confirm the
   alarms clear within their cooldown window (default 5 minutes).

4. **Audit row.** Verify a fresh `release_metadata` row landed with
   the previous version's SHA and a `notes` line containing
   `"rollback"`. The integration test
   [`backend/tests/integration/test_release_metadata.py`](../../backend/tests/integration/test_release_metadata.py)
   pins this contract at unit level.

5. **Restore.** Re-run the dev deploy workflow against the latest
   green SHA so the dev stack is back to head. The rehearsal is over.

## Acceptance criteria for the rehearsal

The rehearsal **passes** when all of the following hold:

- Alarm fires within 5 minutes of the bad-image alias swing.
- Rollback alias swing completes in < 60 s of operator command.
- `/health` returns 200 against the rolled-back alias within 60 s.
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
aws s3 sync frontend/dist "s3://briefed-prod-pwa" --delete
aws cloudfront create-invalidation --distribution-id <dist-id> --paths "/*"
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
