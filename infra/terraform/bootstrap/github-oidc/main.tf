/*
 * Bootstrap — GitHub Actions OIDC trust + deploy role.
 *
 * Run ONCE per AWS account, with admin-level local credentials.
 * Output ``deploy_role_arn`` is the value to drop into the GitHub
 * Environment secret ``AWS_DEPLOY_ROLE_ARN`` for the ``dev`` and ``prod``
 * environments. State for this stack is intentionally local — it is a
 * one-shot, account-level resource that does not benefit from remote
 * state. See README.md in this directory for the full runbook.
 */

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.50"
    }
  }
}

provider "aws" {
  region              = var.region
  allowed_account_ids = [var.aws_account_id]
}

variable "aws_account_id" {
  description = "AWS account ID this role lives in. Bootstrap fails closed if the active credentials don't match."
  type        = string
  default     = "970385384114"
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "github_owner" {
  description = "GitHub org/user that owns the repo."
  type        = string
  default     = "Kartik-Hirijaganer"
}

variable "github_repo" {
  description = "Repo name (no owner prefix)."
  type        = string
  default     = "Briefed"
}

variable "role_name" {
  description = "IAM role name GitHub Actions assumes via OIDC."
  type        = string
  default     = "briefed-gha-deploy"
}

# The GitHub OIDC provider is an account-level singleton (only one per
# URL is allowed). It was created out-of-band by an earlier project, so
# we consume it via a data source rather than re-creating it. If you
# are bootstrapping a fresh AWS account where no provider exists yet,
# create it once with:
#
#   aws iam create-open-id-connect-provider \
#     --url https://token.actions.githubusercontent.com \
#     --client-id-list sts.amazonaws.com \
#     --thumbprint-list ffffffffffffffffffffffffffffffffffffffff
#
# (AWS no longer validates the thumbprint against the JWKS — STS
# verifies the JWT against managed roots — but the field is still
# required by the IAM API. Any 40-char hex value is accepted.)
data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

# Trust policy — only the Briefed repo's workflows running against the
# ``dev`` or ``prod`` GitHub Environments can assume the role. The
# ``environment:`` claim is set by GitHub when a job declares
# ``environment: prod`` (or dev). Adding new environments? Extend the
# ``token.actions.githubusercontent.com:sub`` list below and re-apply.
data "aws_iam_policy_document" "trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [data.aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values = [
        "repo:${var.github_owner}/${var.github_repo}:environment:prod",
        "repo:${var.github_owner}/${var.github_repo}:environment:dev",
      ]
    }
  }
}

resource "aws_iam_role" "deploy" {
  name               = var.role_name
  assume_role_policy = data.aws_iam_policy_document.trust.json
  description        = "Assumed by GitHub Actions to deploy the Briefed stack via Terraform."

  tags = {
    "briefed:managed" = "terraform"
    "briefed:purpose" = "deploy"
  }
}

# Permissions for the deploy role.
#
# Scoping notes:
# - PowerUserAccess covers ECR, Lambda, S3, CloudFront, SQS, SSM, KMS,
#   DynamoDB (state lock), Logs, EventBridge, Route53, ACM, etc. — every
#   service Terraform touches in this repo.
# - It does NOT include IAM. Terraform creates IAM roles for the
#   lambdas, so we attach a tightly-scoped IAM policy alongside.
# - Tighten this later by replacing PowerUserAccess with a hand-rolled
#   policy once the prod resource set is stable. For v1 the trust policy
#   (limited to this repo's environments) is the primary control.
resource "aws_iam_role_policy_attachment" "power_user" {
  role       = aws_iam_role.deploy.name
  policy_arn = "arn:aws:iam::aws:policy/PowerUserAccess"
}

data "aws_iam_policy_document" "iam_for_deploy" {
  # Allow Terraform to manage IAM roles + policies for the briefed-*
  # lambdas it provisions, but nothing outside that name prefix.
  statement {
    effect = "Allow"
    actions = [
      "iam:CreateRole",
      "iam:DeleteRole",
      "iam:GetRole",
      "iam:UpdateRole",
      "iam:UpdateAssumeRolePolicy",
      "iam:PassRole",
      "iam:TagRole",
      "iam:UntagRole",
      "iam:ListRoleTags",
      "iam:AttachRolePolicy",
      "iam:DetachRolePolicy",
      "iam:ListAttachedRolePolicies",
      "iam:PutRolePolicy",
      "iam:DeleteRolePolicy",
      "iam:GetRolePolicy",
      "iam:ListRolePolicies",
    ]
    resources = [
      "arn:aws:iam::${var.aws_account_id}:role/briefed-*",
    ]
  }

  # Read-only access to inspect customer-managed policies the deploy
  # role may attach.
  statement {
    effect = "Allow"
    actions = [
      "iam:GetPolicy",
      "iam:GetPolicyVersion",
      "iam:ListPolicyVersions",
      "iam:ListPolicies",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "iam_for_deploy" {
  name   = "briefed-iam-management"
  role   = aws_iam_role.deploy.id
  policy = data.aws_iam_policy_document.iam_for_deploy.json
}

output "deploy_role_arn" {
  description = "Drop this value into the GitHub Environment secret AWS_DEPLOY_ROLE_ARN."
  value       = aws_iam_role.deploy.arn
}

output "oidc_provider_arn" {
  value = data.aws_iam_openid_connect_provider.github.arn
}
