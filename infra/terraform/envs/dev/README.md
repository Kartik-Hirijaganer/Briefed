# dev environment

One-time bootstrap (state backend — chicken-and-egg with Terraform itself):

```bash
aws cloudformation deploy \
  --template-file ../../bootstrap/state-backend.yaml \
  --stack-name briefed-tf-state-dev \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides Env=dev
```

Then configure `backend.tf` (NOT committed — use the template in
`envs/dev/backend.tf.example`) and run:

```bash
terraform init
terraform plan  -var "image_uri=<ecr-uri>:<sha>"
terraform apply -var "image_uri=<ecr-uri>:<sha>"
```

Before the first apply, upload real secret values (the Terraform module
creates the parameter names with placeholder values; overwrite with real
keys):

```bash
aws ssm put-parameter --name /briefed/dev/openrouter_api_key --type SecureString \
  --value "<key>" --overwrite
# … repeat for supabase_db_url, session_signing_key, google_oauth_client_*, etc.
```

See `docs/operations/runbook.md` (lands in Phase 8) for rollback steps.
