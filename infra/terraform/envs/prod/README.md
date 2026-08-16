# prod environment

This is Briefed's only persistent cloud environment (ADR 0016). Local
development uses Docker and LocalStack rather than a second AWS stack.
Production stores raw MIME when configured (`BRIEFED_STORE_RAW_MIME=1`) and
supports a custom domain once ACM has issued the certificate.

Deploys go through `.github/workflows/deploy-prod.yml`. Manual
operator commands below are for break-glass only.

## One-time bootstrap

```bash
aws --profile personal-admin cloudformation deploy \
  --template-file ../../bootstrap/state-backend.yaml \
  --stack-name briefed-tf-state-prod \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides Env=prod
```

Copy `backend.tf.example` → `backend.tf` (gitignored) with the real
state-bucket + lock-table names.

```bash
AWS_PROFILE=personal-admin terraform init
AWS_PROFILE=personal-admin terraform plan  -var "image_uri=<ecr-uri>:<sha>"
AWS_PROFILE=personal-admin terraform apply -var "image_uri=<ecr-uri>:<sha>"
```

Before the first apply, populate every required SSM parameter with
real production credentials (`/briefed/prod/...`). The Terraform
module creates the parameter names with placeholders.

## Blue/green deploy flow (operator-friendly summary)

1. CI previews and applies the untagged-image ECR lifecycle policy, then builds
   and pushes the image (`:<sha>` + `:<tag>`).
2. Terraform writes a saved plan. The workflow rejects KMS, CloudFront,
   Function URL, or WAF deletion/replacement before applying that exact plan.
3. The saved plan publishes new Lambda versions and moves each `live` alias as
   part of the Terraform apply.
4. CloudFront API smoke checks and runtime-wiring checks run immediately. A
   failed API smoke check moves all aliases back to the captured versions.
5. A no-drift Terraform plan must pass, and
   `python backend/scripts/write_release_metadata.py
   --version v<semver> --git-sha "$GITHUB_SHA"` records the row
   (plan §8 + §19.7 ledger).

## Rollback

The `live` alias is the only thing to flip back. Each deploy publishes a fresh
container-image Lambda version. Briefed does not use SnapStart because AWS does
not support it for container-image functions; rollback depends on retaining the
prior published version.

```bash
PREV=$(aws --profile personal-admin lambda list-versions-by-function \
  --function-name briefed-prod-api \
  --query 'Versions[-2].Version' --output text)
aws --profile personal-admin lambda update-alias --name live \
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
