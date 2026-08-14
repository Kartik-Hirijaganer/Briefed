# infra/

Terraform sources for the AWS side of Briefed. Everything application-level
lives in `backend/` + `frontend/`; everything AWS-level lives here.

```
infra/terraform/
├── modules/
│   ├── lambda-api/        # API Lambda (Mangum + Function URL)
│   ├── lambda-worker/     # worker Lambda (SQS event sources)
│   ├── lambda-fanout/     # fan-out Lambda (EventBridge Scheduler target)
│   ├── sqs/               # per-stage SQS queues + DLQ
│   ├── ssm/               # SSM Parameter Store placeholders
│   ├── s3/                # raw-mime / digests / backups buckets
│   ├── cloudfront/        # PWA CDN + Function URL origin
│   ├── route53/           # hosted zone + records
│   ├── acm/               # TLS certificates (DNS-validated)
│   └── kms/               # two CMKs: token-wrap + content-encrypt
└── envs/
    └── prod/              # sole deployed environment (Terraform root module)
```

## State

Production state is stored in an S3 bucket plus DynamoDB lock table. The
[`state-backend.yaml`](terraform/bootstrap/state-backend.yaml) CloudFormation
template bootstraps them (chicken-and-egg: Terraform cannot create its own
state backend). Bootstrap is a one-time manual step per account.

The committed `prod` root module and deploy workflow are guarded to AWS account
`970385384114` via Terraform `allowed_account_ids`, explicit STS checks, and
`configure-aws-credentials.allowed-account-ids`. Local development continues
to use Docker, Postgres, LocalStack, and Infisical; it does not create a second
paid AWS environment.

## Plans over applies

Production deployment creates a saved Terraform plan, rejects destructive
KMS/CloudFront/Function URL/WAF actions, applies that exact plan, runs runtime
smoke checks, and requires a final no-drift plan.
