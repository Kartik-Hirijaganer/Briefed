# ADR 0016 - Single production cloud environment

- **Date:** 2026-08-12
- **Status:** Accepted
- **Deciders:** Kartik Hirijaganer
- **Related:** ADR 0003, ADR 0004, ADR 0008, ADR 0011

## Context

Briefed was deployed to independent AWS `dev` and `prod` Terraform states even
though it is a personal, low-traffic application. Each state duplicated fixed-
cost resources including two customer-managed KMS keys and a CloudFront WAF.
The live Vercel application routes to the prod CloudFront distribution, prod was
deployed most recently, and the stale dev API had already been stopped by a
zero reserved-concurrency setting.

Local development does not require a persistent cloud environment. PostgreSQL
and AWS-compatible services run locally through Docker and LocalStack, while
Infisical injects application secrets into local processes.

## Decision

Operate exactly one persistent Briefed cloud environment, named `prod`.

1. Production remains the canonical AWS deployment and Terraform state.
2. The former dev database and non-rebuildable objects are archived for 30 days
   before its Terraform state is destroyed.
3. CI validates only the prod Terraform root and GitHub exposes only the prod
   deployment workflow.
4. Local `make dev` remains the development path; it does not imply or create a
   remote AWS dev environment.
5. A second cloud environment requires a new ADR with a cost owner, expiry
   date, and automated teardown policy.

## Consequences

**Benefits**

- Fixed KMS, WAF, CloudFront, logging, and state-backend costs are paid once.
- The live topology and the repository deployment model no longer disagree.
- Fewer credentials, queues, alarms, and Terraform states require maintenance.

**Costs**

- Infrastructure changes cannot be rehearsed in a persistent AWS dev stack.
- Risk is instead controlled with saved Terraform plans, protected-resource
  guards, local validation, Lambda aliases, smoke tests, and rollback.
- Recovery of retired dev data is time-limited to the archive and KMS deletion
  windows documented in the decommission runbook.

## Alternatives considered

- **Keep both environments but disable dev compute.** Rejected. KMS and WAF
  fixed costs remain and configuration continues to drift.
- **Promote dev and destroy prod.** Rejected. Prod is newer and is the origin
  used by the live Vercel deployment.
- **Remove local development configuration.** Rejected. Local Docker,
  LocalStack, and Infisical selectors do not create persistent AWS cost.

## Revisit triggers

- The project gains multiple operators who require isolated release rehearsal.
- Production traffic or compliance requirements demand a separately controlled
  pre-production environment.
- Ephemeral preview infrastructure can be created with mandatory TTL teardown
  at materially lower risk than direct production validation.
