# GitHub Actions OIDC bootstrap

Run **once per AWS account**, with admin-level local credentials.

This stack creates:
- A single deploy role (`briefed-gha-deploy`) trusted only by workflows in
  this repo running against the `dev` or `prod` GitHub Environments.
- Permissions: `PowerUserAccess` + a scoped IAM policy that lets
  Terraform create / update the lambda execution roles (`briefed-*`).

It **consumes** the existing GitHub OIDC identity provider
(`token.actions.githubusercontent.com`) via a `data` source. The OIDC
provider is an account-level singleton — if no provider exists yet in
your account, create it once with the `aws iam
create-open-id-connect-provider` command shown in [main.tf](main.tf)
before running `terraform apply`.

The role + OIDC provider for account `970385384114` were already
created out-of-band via the AWS CLI on 2026-04-26 — the role ARN is
`arn:aws:iam::970385384114:role/briefed-gha-deploy`. This Terraform
stack exists so the same setup is reproducible from code in any other
account; running `terraform apply` against `970385384114` would error
on `aws_iam_role.deploy` (already exists) and would need a one-time
`terraform import` first.

State is local on purpose — this is a one-shot, account-level resource.

## One-time apply

```bash
cd infra/terraform/bootstrap/github-oidc
aws sts get-caller-identity   # confirm you are in account 970385384114
terraform init
terraform apply
```

Copy the `deploy_role_arn` output and store it as the GitHub Environment
secret `AWS_DEPLOY_ROLE_ARN` for both `prod` and `dev`. See the root
[README.md](../../../../README.md) section "GitHub Secrets" for the full
list of secrets the deploy + CI workflows need.

## Tightening later

`PowerUserAccess` is intentionally broad for v1 — the trust policy
(`environment:prod` / `environment:dev`, this repo only) is the primary
control. When the prod resource set stabilizes, replace the managed
policy attachment in [main.tf](main.tf) with a hand-rolled policy
limited to the resource ARNs Terraform actually manages.
