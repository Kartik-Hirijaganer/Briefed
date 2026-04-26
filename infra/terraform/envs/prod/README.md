# prod environment

The prod stack mirrors `envs/dev/main.tf` — same module graph, same
KMS CMKs, same alarms — with stricter retention defaults
(`BRIEFED_STORE_RAW_MIME=1`) and a custom domain wired in once ACM has
issued the certificate.

Deploys go through `.github/workflows/deploy-prod.yml`. Manual
operator commands below are for break-glass only.

## One-time bootstrap

```bash
aws cloudformation deploy \
  --template-file ../../bootstrap/state-backend.yaml \
  --stack-name briefed-tf-state-prod \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides Env=prod
```

Copy `backend.tf.example` → `backend.tf` (gitignored) with the real
state-bucket + lock-table names.

```bash
terraform init
terraform plan  -var "image_uri=<ecr-uri>:<sha>"
terraform apply -var "image_uri=<ecr-uri>:<sha>"
```

Before the first apply, populate every required SSM parameter with
real production credentials (`/briefed/prod/...`). The Terraform
module creates the parameter names with placeholders.

## Blue/green deploy flow (operator-friendly summary)

1. CI builds the image and pushes to ECR (`:<sha>` + `:<tag>`).
2. `terraform apply -var image_uri=...` publishes a new Lambda
   version. The `live` alias does not move yet.
3. Smoke test against the new `$LATEST` qualifier
   (`/health` + `/api/v1/digest/today` returning a sane shape).
4. `aws lambda update-alias --name live --function-version <new>`
   for api + worker + fanout. This is the atomic cutover.
5. `python backend/scripts/write_release_metadata.py
   --version v<semver> --git-sha "$GITHUB_SHA"` records the row
   (plan §8 + §19.7 ledger).

## Rollback

The `live` alias is the only thing to flip back. Each deploy publishes
a fresh version; previous versions remain available until SnapStart
GC trims them (~30 days).

```bash
PREV=$(aws lambda list-versions-by-function \
  --function-name briefed-prod-api \
  --query 'Versions[-2].Version' --output text)
aws lambda update-alias --name live \
  --function-name briefed-prod-api --function-version "$PREV"
# Repeat for briefed-prod-worker and briefed-prod-fanout.
```

Then write a fresh `release_metadata` row noting the rollback target
(see [`docs/operations/rollback.md`](../../../../docs/operations/rollback.md)).

## Outputs of interest

- `function_url` — Lambda Function URL (CloudFront origin).
- `cloudfront_domain` — distribution domain for the PWA + API.
- `pwa_bucket` — S3 bucket the frontend deploy step writes to.
- `dashboard_name` — CloudWatch dashboard for the on-call view.
- `alarm_topic_arn` — SNS topic for paging alerts.
- `api_function_name`, `worker_function_name`, `fanout_function_name`
  — used by the rollback runbook.
