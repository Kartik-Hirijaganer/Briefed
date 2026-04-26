# Security policy

## Supported versions

Briefed is pre-1.0.0 during Phase 0. Once 1.0.0 ships, security fixes will
land on the latest minor release only.

## Reporting a vulnerability

**Please do not open a public GitHub issue for security reports.**

Send details to `security@briefed.example` (placeholder — replace with the
real mailbox before the 1.0.0 tag). Include:

- A description of the issue and its impact.
- Steps to reproduce, ideally with a minimal PoC.
- Your preferred contact method and timeline expectations.

You will receive an acknowledgement within 72 hours. Fix-then-disclose
timing is negotiated in the reply.

## Scope

In scope: this repository's backend, frontend, infra Terraform, and the
deployed application at domains documented in `docs/operations/`.

Out of scope: Google / Anthropic / Gemini / AWS service vulnerabilities
(report those to the respective vendors); social engineering; physical
access.

## Threat model

Summary in `docs/security/threat-model.md` (filled in Phase 8). Highlights:

- Prompt injection via email bodies is treated as expected adversarial
  input; content is delimited with `<untrusted_email>` tags and the eval
  suite includes adversarial fixtures (plan §19.9).
- OAuth refresh tokens are envelope-encrypted under a customer-managed
  KMS CMK (ADR 0008); content columns use a second CMK (§20.10).
