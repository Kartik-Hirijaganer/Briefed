# infra/

Terraform sources for the AWS side of Briefed. Everything application-level
lives in `backend/` + `frontend/`; everything AWS-level lives here.

```
infra/terraform/
├── modules/
│   ├── lambda-api/        # API Lambda (Mangum + SnapStart + Function URL)
│   ├── lambda-worker/     # worker Lambda (SQS event sources + SnapStart)
│   ├── lambda-fanout/     # fan-out Lambda (EventBridge Scheduler target)
│   ├── sqs/               # per-stage SQS queues + DLQ
│   ├── ssm/               # SSM Parameter Store placeholders
│   ├── s3/                # raw-mime / digests / backups buckets
│   ├── cloudfront/        # PWA CDN + Function URL origin
│   ├── route53/           # hosted zone + records
│   ├── acm/               # TLS certificates (DNS-validated)
│   └── kms/               # two CMKs: token-wrap + content-encrypt
└── envs/
    └── dev/               # dev environment composition (Terraform root module)
```

## State

State is stored in an S3 bucket + DynamoDB lock table per environment;
bootstrap script at `infra/terraform/envs/dev/bootstrap.sh` creates them
with `aws cloudformation deploy` (chicken-and-egg: Terraform can't create
its own state backend). Bootstrap is a one-time manual step per account.

The committed `dev` root module and deploy workflow are guarded to AWS
account `970385384114` via Terraform `allowed_account_ids` and
`configure-aws-credentials.allowed-account-ids`.

## Plans over applies

CI runs `terraform plan` on every PR; `terraform apply` happens only from
a protected deploy branch with manual approval. `main` is **never** auto-
applied.
