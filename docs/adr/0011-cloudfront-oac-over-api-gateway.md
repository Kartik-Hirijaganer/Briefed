# ADR 0011 - CloudFront OAC over API Gateway for API edge hardening

- **Date:** 2026-05-30
- **Status:** Accepted
- **Deciders:** Kartik Hirijaganer

## Context

Briefed is a single-tenant, cookie-authenticated application served
through CloudFront. The frontend calls the backend as a same-origin API,
and the API Lambda is exposed through a Lambda Function URL behind the
CloudFront distribution.

The Function URL used `authorization_type = "NONE"`, which made the
origin directly reachable by anyone who learned the Function URL host.
Direct origin access bypasses CloudFront security headers, cache behavior,
and the WAF policy attached to the distribution. The edge needs to
be the only supported caller of the Function URL.

## Decision

Keep the Lambda Function URL as the API origin and require AWS IAM
authorization on it. CloudFront will call the origin through Origin Access
Control (OAC), with `origin_type = "lambda"`, `signing_behavior =
"always"`, and SigV4 signing enabled for every origin request.

The Lambda Function URL will use `authorization_type = "AWS_IAM"`.
The Lambda resource-based policy will grant only the
`cloudfront.amazonaws.com` service principal, scoped to the CloudFront
distribution ARN, both required invoke permissions:

- `lambda:InvokeFunctionUrl`
- `lambda:InvokeFunction`

Viewer authentication remains cookie-based. CloudFront owns the SigV4
`Authorization` header on origin requests; the application does not use
viewer-supplied bearer tokens for API authentication.

Attach AWS WAF to the CloudFront distribution as the edge enforcement
point. The initial policy blocks high-rate IPs and runs
`AWSManagedRulesCommonRuleSet` in COUNT mode until normal traffic has
been observed.

## Consequences

**Benefits**

- Direct Function URL access is rejected unless the caller can produce a
  valid SigV4 request authorized by the Lambda resource policy.
- CloudFront becomes the enforced API edge, so security headers, routing
  behavior, cache behavior, and WAF controls cannot be bypassed by
  calling the origin directly.
- The architecture preserves the existing single-origin Lambda deployment
  chosen in ADR 0003 and avoids adding an unused managed API layer.
- OAC uses AWS-managed request signing rather than an app-tier shared
  origin secret that Briefed would need to store, rotate, and validate.

**Costs**

- Body-bearing API writes must include `x-amz-content-sha256` so
  CloudFront can forward a Lambda-compatible SigV4 request.
- Deployment and smoke tests must validate the CloudFront URL, not the raw
  Function URL.
- The Lambda resource policy needs two CloudFront permissions, scoped to
  the distribution ARN, to satisfy current Function URL authorization
  requirements.
- OAC failures behind the distribution can be obscured by CloudFront
  custom error responses, so diagnostics must validate response content,
  not only HTTP status.
- WAF adds a small fixed monthly cost and should be tuned from COUNT mode
  before managed rules block traffic.

## Alternatives considered

- **API Gateway HTTP API.** Rejected. It is public by default and still
  needs explicit lock-down to prevent bypass. Its managed features
  (JWT authorizers, throttling, request validation, native access logs)
  are not used by the current single-tenant, cookie-authenticated app.
- **API Gateway REST API.** Rejected. Usage plans, API keys, and the
  larger REST API feature set add operational surface without a current
  product requirement.
- **Origin secret header.** Rejected. CloudFront could inject a shared
  header and FastAPI could reject requests that lack it, but that creates
  an app-tier secret, rotation procedure, and middleware path. OAC provides
  the same origin-binding property through AWS-managed signing.
- **Status quo `NONE`.** Rejected. A publicly callable Function URL leaves
  the origin-bypass gap open.

## Revisit triggers

- Briefed becomes a hosted multi-tenant SaaS and needs usage plans,
  per-tenant throttling, or JWT authorizers.
- Briefed exposes public API keys or third-party API access.
- Edge request validation becomes a hard requirement.
- CloudFront OAC for Lambda Function URLs no longer satisfies the required
  origin-isolation or diagnostic needs.
