# Plan — API Edge Hardening: CloudFront OAC + SigV4 over the Lambda Function URL

- **Date:** 2026-05-30
- **Author:** Kartik Hirijaganer
- **Status:** Ready to implement
- **Introduces:** ADR 0011 (Function URL + OAC vs API Gateway); relates to [ADR 0003](../../docs/adr/0003-lambda-snapstart-over-fargate.md) (the front door was chosen there).
- **Blast radius:** Terraform (`cloudfront` + `lambda-api` modules, both env roots) + frontend (`api/client.ts` + offline-queue replay attach `x-amz-content-sha256` on body-bearing writes — see §2) + 2 CI smoke steps + docs.

---

## 1. Goal

Close the **origin-bypass gap**: today the API Lambda Function URL is publicly reachable
(`authorization_type = "NONE"`) and nothing ties it to CloudFront, so anyone who learns the
Function URL host can hit `/api/*` directly — bypassing the CloudFront security-headers policy,
caching rules, and any future WAF. We will make **CloudFront the only caller** of the Function URL
using **Origin Access Control (OAC) + SigV4 signing** (`authorization_type = "AWS_IAM"`), the clean
modern pattern (GA April 2024) — *not* by introducing API Gateway, which would have the same public
posture by default and buy us no feature we use at single-tenant scale.

Secondary cleanups bundled in because they touch the same surface:
- Remove the dead `cors { allow_origins = ["*"] }` block on the Function URL.
- Fix the two CI smoke tests that currently curl the raw Function URL (they break under `AWS_IAM`).
- Write **ADR 0011** documenting "Function URL + OAC vs API Gateway HTTP API" — *the highest-signal
  artifact for the resume*: it shows the trade-off was reasoned, not defaulted.
- **(Optional)** Add AWS WAF on the CloudFront distribution — strong security signal, but adds cost
  (Phase 7).

---

## 2. Critical constraints (AWS-documented — handle these or writes break)

Three properties of CloudFront OAC over a Lambda Function URL drive non-obvious work in this plan. They
are AWS-documented, not optional — each maps to a phase below.

1. **Body-bearing requests must carry `x-amz-content-sha256`.** CloudFront OAC SigV4-signs origin requests
   but does **not** hash the request body for a Lambda origin (unlike S3). The viewer/browser must compute
   the SHA-256 of the body and send it in `x-amz-content-sha256`, or the signature CloudFront forwards won't
   match and the Function URL returns `403`. ([CloudFront Lambda-OAC guide](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-restricting-access-to-lambda.html):
   *"If you use `PUT` or `POST` methods with your Lambda function URL, your users must compute the SHA256 of
   the body and include the payload hash value of the request body in the `x-amz-content-sha256` header …
   Lambda doesn't support unsigned payloads."*) Every write we have carries a body (`POST /api/v1/runs`,
   `POST /unsubscribes/{id}/confirm|dismiss`, `PATCH /preferences`, `PATCH /profile/me`,
   `PATCH /profile/me/schedule`, `PATCH /accounts/{id}`). → **Phase 3** (frontend).
2. **The Function URL needs two IAM grants** — `lambda:InvokeFunctionUrl` **and** `lambda:InvokeFunction`.
   ([Lambda function URL auth](https://docs.aws.amazon.com/lambda/latest/dg/urls-auth.html): *"Starting in
   October 2025, new function URLs will require both `lambda:InvokeFunctionUrl` and `lambda:InvokeFunction`
   permissions."*) AWS's OAC guide shows two `add-permission` calls for the `cloudfront.amazonaws.com`
   principal. → **Phase 2h** (two `aws_lambda_permission` resources).
3. **The distribution masks origin `403`s.** `custom_error_response` rewrites 403/404 → `/index.html` (200)
   distribution-wide ([cloudfront/main.tf:125-136](../../infra/terraform/modules/cloudfront/main.tf)), so a
   broken OAC surfaces as **`200` + HTML where JSON was expected**, not a clean `403`. This shapes the smoke
   test (**Phase 4** — validate JSON, not status) and the UAT diagnostic (**Phase 6**). A clean `403` only
   appears on a **direct** Function-URL hit, which bypasses `custom_error_response`.

---

## 3. Current state (verified, with file:line references)

| Fact | Evidence |
|---|---|
| Function URL is unauthenticated | [`modules/lambda-api/main.tf:154`](../../infra/terraform/modules/lambda-api/main.tf) — `authorization_type = "NONE"` |
| Function URL is on the `live` alias | `aws_lambda_function_url.this` has `qualifier = aws_lambda_alias.live.name` (`main.tf:151-153`) |
| No origin secret ties CloudFront → Lambda | CloudFront lambda `origin {}` block has only `custom_origin_config`, no `custom_header` ([`modules/cloudfront/main.tf:144-153`](../../infra/terraform/modules/cloudfront/main.tf)) |
| Function URL CORS is wide open | `cors { allow_origins = ["*"] }` (`modules/lambda-api/main.tf:156-164`) |
| App auth is cookie-based, **not** `Authorization` header | `briefed_session` signed cookie ([`backend/app/api/session.py:23`](../../backend/app/api/session.py), [`backend/app/api/deps.py:45`](../../backend/app/api/deps.py)); no `Authorization`/`Bearer` in `frontend/src` |
| Frontend is same-origin via CloudFront | `baseUrl: import.meta.env.VITE_API_BASE ?? ''` ([`frontend/src/api/client.ts:77`](../../frontend/src/api/client.ts)) → relative `/api/v1/...` calls |
| `/api/*` + `/openapi.json` already route to the Lambda origin | `ordered_cache_behavior` (`modules/cloudfront/main.tf:166-189`); uses managed `AllViewerExceptHostHeader` origin-request policy (`:176`) |
| `/health` is **top-level**, not under `/api/*` | `@app.get("/health")` ([`backend/app/main.py:61`](../../backend/app/main.py)) — *not reachable through the CloudFront `/api/*` behavior* |
| S3 origin already uses OAC | `aws_cloudfront_origin_access_control "pwa"` (`modules/cloudfront/main.tf:53-58`) + bucket policy scoped to distribution ARN ([`envs/prod/main.tf:175-192`](../../infra/terraform/envs/prod/main.tf)) — **we mirror this pattern for Lambda** |
| Deploy smoke tests curl the raw Function URL | [`deploy-prod.yml:273`](../../.github/workflows/deploy-prod.yml), [`deploy-dev.yml:110`](../../.github/workflows/deploy-dev.yml) — `curl "${URL}health"` where `URL=$(terraform output -raw function_url)` |
| dev mirrors prod | `envs/dev/main.tf` has the same module graph, same `us_east_1` provider alias, same `data.aws_caller_identity` + S3-policy pattern |
| Provider supports lambda OAC | both modules pin `aws >= 5.50`; `origin_access_control_origin_type = "lambda"` needs ≥ 5.41 ✅ |

**Why OAC is safe here (precondition check):** OAC signs the origin request and owns the
`Authorization` header (it carries the SigV4 signature). The known failure mode is a viewer-supplied
`Authorization` header conflicting with the signature. Briefed authenticates with a **cookie**, never
an `Authorization` header — verified above — so the managed `AllViewerExceptHostHeader` origin-request
policy already in place is correct (it sends the origin its own `Host`, required for SigV4, and we have
no `Authorization` header to clobber). **No origin-request-policy change is required.** (Optional
belt-and-braces variant in Phase 2, step 2d-alt.)

---

## 4. The decision (full rationale → ADR 0011)

**Chosen:** keep the Lambda Function URL; enforce CloudFront-only access via OAC + `AWS_IAM` SigV4 signing.

**Rejected — API Gateway HTTP API:** it is *also* public by default and needs the same lock-down
(origin secret / WAF / IAM auth), so it does not "fix" the bypass. Its real value is managed features —
usage plans, API keys, request validation, per-route throttling, custom/JWT authorizers, native access
logs — none of which a single-tenant, cookie-authed app uses. Adding it would be infrastructure we do
not exercise. (CloudFront already provides TLS, custom domain, and the security-headers policy.)

**Rejected — origin secret header:** CloudFront injects a shared `X-Origin-Secret` custom header and
FastAPI middleware rejects requests lacking it. Works, but introduces an app-tier secret to rotate and
a code path to maintain; OAC achieves the same with AWS-managed signing.

---

## 5. Scope

**In scope**
1. ADR 0011 (the decision record).
2. Terraform: Lambda OAC + attach to distribution + flip Function URL to `AWS_IAM` + grant CloudFront **two** invoke permissions — in `cloudfront` module, `lambda-api` module, and **both** env roots.
3. Frontend: attach `x-amz-content-sha256` on body-bearing writes (the live client + the offline-queue replay path).
4. Remove the dead Function URL `cors {}` block.
5. Fix both CI smoke tests to probe through CloudFront.
6. README + ADR-index docs touch-ups.

**Out of scope** (tracked separately — see §11 Related findings)
- AWS WAF — included as **optional** Phase 7.
- The ADR 0003 ↔ code **SnapStart drift** (ADR says "SnapStart on"; the API Lambda comment at
  `modules/lambda-api/main.tf:125-131` says SnapStart is *off* because container images don't support it).
- Any change to the FastAPI app, routing, or `/health` location.

---

## 6. Work breakdown — explicit changes

> File paths are relative to repo root. Each step lists the exact edit and its rationale.
> Phases 1–4 implement the change, 5–6 verify it, Phase 7 (WAF) is optional, Phase 8 is docs.

### Phase 1 — ADR 0011 (the decision record)

**New file:** `docs/adr/0011-cloudfront-oac-over-api-gateway.md`

Use the existing ADR shape (see `0003`): Date / Status: Accepted / Deciders, then Context, Decision,
Consequences (Benefits / Costs), Alternatives considered, Revisit triggers.

- **Context:** single-tenant, cookie-auth, CloudFront-fronted; Function URL was `NONE` → bypassable.
- **Decision:** Function URL stays; `authorization_type = "AWS_IAM"`; CloudFront OAC (`origin_type = lambda`,
  `signing_behavior = always`, `sigv4`) signs every origin request; resource-based policy grants only
  `cloudfront.amazonaws.com` (scoped to the distribution ARN) both `lambda:InvokeFunctionUrl` and
  `lambda:InvokeFunction`.
- **Alternatives considered:** API Gateway HTTP API (rejected — same public posture, unused features);
  API Gateway REST API (rejected — overkill; usage plans/API keys not needed); origin secret header
  (rejected — app-tier secret to rotate); status quo `NONE` (rejected — bypass).
- **Revisit triggers:** multi-tenant SaaS (re-evaluate API Gateway for usage plans + per-tenant throttling
  + JWT authorizers); need for public API keys; need for edge request validation.

Also update the ADR index in `docs/adr/README.md` (and the stale "0001–0008" mentions in the root README —
see Phase 8).

### Phase 2 — Terraform: OAC + SigV4 enforcement

**2a. `modules/cloudfront/main.tf` — add a Lambda OAC** (mirrors the existing `pwa` S3 OAC at `:53-58`):

```hcl
resource "aws_cloudfront_origin_access_control" "lambda" {
  name                              = "${var.name}-lambda-oac"
  description                       = "Signs CloudFront -> API Lambda Function URL requests (SigV4)."
  origin_access_control_origin_type = "lambda"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}
```

**2b. `modules/cloudfront/main.tf` — attach the OAC to the Lambda origin** (`:144-153`). Keep
`custom_origin_config` — a Function URL is an HTTPS custom origin; OAC adds signing on top:

```hcl
  origin {
    origin_id                = local.lambda_origin_id
    domain_name              = var.lambda_function_url_host
    origin_access_control_id = aws_cloudfront_origin_access_control.lambda.id   # <-- ADD
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }
```

**2c. Origin-request policy — NO CHANGE.** Keep managed `AllViewerExceptHostHeader` on the `/api/*` and
`/openapi.json` behaviors (`:176`, `:187`). It is already correct for OAC (sends the origin its own `Host`,
required for SigV4) and the app sends no `Authorization` header to conflict (see §3 precondition check).

**2d-alt (OPTIONAL belt-and-braces).** If you want to defend against a viewer-supplied `Authorization`
header clobbering the SigV4 signature, replace the managed policy on the two Lambda behaviors with a
custom policy that forwards everything except `Host` and `Authorization`:

```hcl
resource "aws_cloudfront_origin_request_policy" "api" {
  name = "${var.name}-api-origin-req"
  cookies_config       { cookie_behavior = "all" }
  query_strings_config { query_string_behavior = "all" }
  headers_config {
    header_behavior = "allExcept"
    headers { items = ["authorization"] }   # VERIFY whether "host" can/should also be listed for your provider version
  }
}
```
> ⚠️ Verify `allExcept` Host semantics against the pinned provider before adopting 2d-alt — the managed
> `AllViewerExceptHostHeader` is the safe default and 2c (no change) is recommended.

**2e. `modules/lambda-api/main.tf` — flip the Function URL to IAM auth** (`:154`). Wire this through a
variable so the rollout (§7) can flip it with `-var`, not a code edit:

```hcl
variable "function_url_auth_mode" {
  type    = string
  default = "NONE"   # rollout Step 1 keeps NONE; Step 2 passes -var function_url_auth_mode=AWS_IAM
}

# in aws_lambda_function_url.this:
  authorization_type = var.function_url_auth_mode   # CloudFront OAC signs (SigV4); AWS_IAM => direct access 403
```

**2f. `modules/lambda-api/main.tf` — remove the dead CORS block** (`:156-164`). Rationale: the frontend
is same-origin through CloudFront (relative `baseUrl`), so browser CORS never applied to the Function URL;
under `AWS_IAM` a browser can't reach it directly anyway. (Alternative: tighten `allow_origins` to the app
origin instead of deleting — but deletion is cleaner since it's unused.)

**2g. (cleanliness) `modules/lambda-api/main.tf` — expose the alias name** so the env-root permission
avoids a magic string:

```hcl
output "alias_name" {
  value       = aws_lambda_alias.live.name   # "live"
  description = "Alias the Function URL is published on; used for the CloudFront invoke permission qualifier."
}
```

**2h. `envs/prod/main.tf` AND `envs/dev/main.tf` — grant CloudFront permission to invoke the signed URL.**
Place next to the existing S3 bucket policy (`envs/prod/main.tf:175-192`); reuse the existing
`data.aws_caller_identity.current` and `module.cloudfront.distribution_id` (no new output needed — mirrors
the S3 `AWS:SourceArn` pattern at `:187`):

```hcl
# AWS (Oct 2025+) requires BOTH actions on a function URL, and the CloudFront OAC
# guide shows two add-permission calls for the cloudfront.amazonaws.com principal.
# source_arn (= this distribution) scopes both grants. See §2.
resource "aws_lambda_permission" "cloudfront_invoke_url" {
  statement_id           = "AllowCloudFrontInvokeFunctionUrl"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = module.api.function_name
  qualifier              = module.api.alias_name            # "live"
  principal              = "cloudfront.amazonaws.com"
  function_url_auth_type = "AWS_IAM"
  source_arn             = "arn:aws:cloudfront::${data.aws_caller_identity.current.account_id}:distribution/${module.cloudfront.distribution_id}"
}

resource "aws_lambda_permission" "cloudfront_invoke_function" {
  statement_id  = "AllowCloudFrontInvokeFunction"
  action        = "lambda:InvokeFunction"
  function_name = module.api.function_name
  qualifier     = module.api.alias_name                     # "live"
  principal     = "cloudfront.amazonaws.com"
  source_arn    = "arn:aws:cloudfront::${data.aws_caller_identity.current.account_id}:distribution/${module.cloudfront.distribution_id}"
}
```
> Both grants are mandatory for new function URLs (AWS, Oct 2025+). AWS's CloudFront-principal OAC example
> uses these two plain permissions; the `lambda:InvokedViaFunctionUrl` condition (seen only in AWS's
> *cross-account user* example) is optional hardening — if you add it, confirm the exact `aws_lambda_permission`
> argument against the provider schema first (don't assume the name exists).

**2i. `envs/{dev,prod}/main.tf` — update the `function_url` output description** (`:214-216` / dev `:211-212`)
to note it is no longer directly callable without SigV4 signing (kept for reference/debugging only).

### Phase 3 — Frontend: sign body-bearing writes with `x-amz-content-sha256`

**Why — the one application-code change in this plan.** Per §2 Constraint 1, CloudFront OAC does not hash
the request body for a Lambda Function URL, so the browser must send `x-amz-content-sha256: <hex SHA-256 of
the exact body bytes>` on `PUT`/`POST`/`PATCH`. Missing/incorrect → the Function URL rejects with `403`
(which `custom_error_response` then masks to `/index.html`).

**Where:**
- [`frontend/src/api/client.ts`](../../frontend/src/api/client.ts) — add an `openapi-fetch` request middleware that, for body-bearing methods, computes `crypto.subtle.digest('SHA-256', bytes)`, hex-encodes, and sets `x-amz-content-sha256`. Hash the **exact serialized bytes** that get sent (post-`JSON.stringify`).
- [`frontend/src/offline/mutations`](../../frontend/src/offline/) — the offline-queue **replay** path also issues `POST`/`PATCH` and must attach the same header on flush.
- Body-less `POST`s (e.g. `POST /unsubscribes/{id}/confirm`) use the SHA-256 of the empty string (`e3b0c442…`); set it explicitly.

**Caveats:** `crypto.subtle` needs a secure context (fine — the PWA is HTTPS via CloudFront; can't be tested
over local `http://`). The `/api/*` behavior's `AllViewerExceptHostHeader` policy forwards the header to the
origin. ✅

**Verify:** body-bearing writes (`POST /api/v1/runs`, `PATCH /api/v1/preferences`, profile/schedule
`PATCH`es) succeed end-to-end through CloudFront — not just `200` GETs. Without the header they fail and the
failure is masked to HTML, so assert on JSON / `Content-Type` (see Phase 4).

### Phase 4 — CI smoke tests (must change or deploys fail)

Under `AWS_IAM`, `curl "${function_url}health"` returns **403**. Both deploy workflows fail at the smoke
step (and prod would then auto-rollback). `/health` is top-level so it is NOT reachable via the CloudFront
`/api/*` behavior — but `/openapi.json` already is. Probe the full hardened chain instead:

**`deploy-prod.yml` (`:269-274`)** — replace the smoke step body:
```yaml
      - name: Smoke check live API through CloudFront
        id: smoke
        working-directory: ${{ env.TF_DIR }}
        run: |
          DOMAIN=$(terraform output -raw cloudfront_domain)
          # custom_error_response rewrites origin 403/404 -> /index.html (200), so `--fail`
          # alone can PASS on masked HTML. Assert the body is real OpenAPI JSON:
          curl -fsS --retry 5 --retry-delay 3 "https://${DOMAIN}/openapi.json" \
            | jq -e '.openapi and .paths' >/dev/null
          # Exercise a body-bearing write end-to-end (must carry x-amz-content-sha256 — §2/Phase 3).
          # A masked edge 403 returns text/html; the app returns application/json — assert JSON:
          ct=$(curl -s -o /dev/null -w '%{content_type}' -X POST \
            -H 'content-type: application/json' \
            -H "x-amz-content-sha256: $(printf '{}' | shasum -a 256 | cut -d' ' -f1)" \
            -d '{}' "https://${DOMAIN}/api/v1/runs")
          case "$ct" in application/json*) : ;; *) echo "POST masked/blocked at edge (got $ct)"; exit 1 ;; esac
```

**`deploy-dev.yml` (`:108-111`)** — same shape, using the dev `cloudfront_domain` output.

Notes:
- This is a *stronger* smoke test: it exercises CloudFront → OAC SigV4 → Function URL → Mangum → FastAPI
  end-to-end, validating the OAC path itself.
- The prod auto-rollback step keying off `steps.smoke` is unchanged (`deploy-prod.yml:276-283`).
- **Alternative** if you prefer a dedicated liveness path over `/openapi.json`: add an
  `ordered_cache_behavior` for `/health` → Lambda origin (mirror the `/openapi.json` block at
  `modules/cloudfront/main.tf:180-189`) and probe `https://${DOMAIN}/health`. Slightly more infra; not
  required.

### Phase 5 — Testing strategy (what's testable locally vs. only in AWS)

> **Read this first — the honest constraint.** This change is entirely about CloudFront → OAC → SigV4 →
> Lambda Function URL, which is **AWS-managed edge infrastructure that cannot be emulated in this repo's
> local stack**. The project's LocalStack only runs `sqs,ssm,s3,kms,events,scheduler`
> (`docker-compose.yml:34`) — **no CloudFront, no Lambda Function URL, no OAC**. And `make dev` runs the
> app via uvicorn (`BRIEFED_RUNTIME=local`), which serves `app.main:app` **directly** — it never goes
> through the Function URL or CloudFront. So a working local app proves *nothing* about this change.
>
> "Testing locally" therefore means two distinct things: **(Tier 0) static validation on your machine**,
> and **(Tier 2) behavioral validation in the `dev` AWS environment** — your de-facto staging gate before
> prod. There is no middle path that exercises OAC without real AWS.
>
> Use `AWS_PROFILE=personal-admin` for every AWS-touching command (account 970385384114).

| Tier | Runs where | Proves | AWS? |
|---|---|---|---|
| 0 — Static | your machine | HCL is valid, provider accepts the new resources/args | No (offline after provider cache) |
| 1 — Plan | your machine → AWS read | the diff is exactly what's intended, distribution updates **in place** | Read-only |
| 2 — Dev apply + curl | `dev` env | OAC actually blocks direct access and CloudFront actually works | **Yes (mutates dev)** |
| 3 — SigV4 isolation (optional) | `dev` env | the Function URL enforces + accepts SigV4 independent of CloudFront | Yes |

**Tier 0 — Static, fully offline (truly local).** Catches the most likely mistakes (typo'd OAC origin
type, wrong `aws_lambda_permission` args, malformed origin block) without touching AWS — `terraform
validate` checks config against provider schemas, not the cloud:
```bash
make tf-fmt          # format
make tf-validate     # fmt -check + `terraform validate` for dev + prod (Makefile:207-211)
make test            # confirm no app regression (frontend tests cover the new x-amz-content-sha256 helper)
# optional full CI parity:
make ci              # lint → test → coverage → docs drift → security → tf-validate (Makefile:237-265)
```

**Tier 1 — Plan review (read-only against AWS, mutates nothing).**
```bash
AWS_PROFILE=personal-admin \
  terraform -chdir=infra/terraform/envs/dev plan -var "image_uri=<current-dev-image-uri>"
```
Assert the diff is **exactly**:
- `+ aws_cloudfront_origin_access_control.lambda`
- `~ aws_cloudfront_distribution.this` — lambda origin gains `origin_access_control_id` (+ new origin-request policy only if you chose 2d-alt)
- `~ aws_lambda_function_url.this` — `authorization_type` `NONE → AWS_IAM`, `cors` block removed
- `+ aws_lambda_permission.cloudfront_invoke_url` **and** `+ aws_lambda_permission.cloudfront_invoke_function` (both grants required — see §2)
- `+ output alias_name`

🚩 **Critical:** the distribution must show **`~` update in-place, not `-/+` replace.** A replace mints a
new CloudFront domain → broken DNS/links. If you see a replace, stop and investigate before applying.

**Tier 2 — Dev environment = the real integration test (cannot be done locally).** Run the two-step
rollout from §7 against `dev`, then the curl matrix:
```bash
export AWS_PROFILE=personal-admin
DOMAIN=$(terraform -chdir=infra/terraform/envs/dev output -raw cloudfront_domain)
FN=$(terraform -chdir=infra/terraform/envs/dev output -raw function_url)

# After Step 1 (OAC + permissions added, auth still NONE):
# NOTE: custom_error_response masks an origin 403 -> /index.html(200), so validate JSON, not status.
curl -fsS "https://${DOMAIN}/openapi.json" | jq -e '.openapi and .paths' >/dev/null && echo "CDN OK (signed)"
curl -s -o /dev/null -w '%{http_code}\n' "${FN}health"                              # expect 200 (still open)

# After Step 2 (auth flipped to AWS_IAM, CORS removed):
curl -fsS "https://${DOMAIN}/openapi.json" | jq -e '.openapi and .paths' >/dev/null && echo "CDN OK (enforced)"
curl -s -o /dev/null -w '%{http_code}\n' "${FN}health"                              # expect 403 ✅ (direct hit is NOT masked)
```
Then in a browser against the dev CloudFront domain: load the app, complete Gmail OAuth login (confirm the
`briefed_session` cookie is set), and confirm an authenticated `/api/v1/...` call **and a body-bearing write**
(Scan Now / a Preferences toggle) both succeed. **Promote to prod only after dev passes.**

**Tier 3 — Optional: isolate "Function URL IAM auth" from "CloudFront OAC".** After Step 2 on dev, prove
the URL enforces *and* accepts SigV4 independently of CloudFront. `curl 8.7.1` (installed) supports
`--aws-sigv4`; `awscurl` is not installed but handles SSO/temp session tokens more cleanly:
```bash
# Cleanest (auto-handles temp creds from the profile):
pip install awscurl
awscurl --service lambda --region us-east-1 --profile personal-admin "${FN}health"   # expect 200

# No-install alternative (must export creds incl. session token for SSO/temp creds):
curl --aws-sigv4 "aws:amz:us-east-1:lambda" \
  --user "$AWS_ACCESS_KEY_ID:$AWS_SECRET_ACCESS_KEY" \
  -H "x-amz-security-token: $AWS_SESSION_TOKEN" \
  "${FN}health"                                                                      # expect 200
```
⚠️ **Interpret carefully:** this signs as *your* IAM identity (admin), **not** the CloudFront service
principal. It validates "the Function URL now requires and accepts SigV4," but it does **not** validate
the CloudFront-scoped resource policy we add (`Principal: cloudfront.amazonaws.com`, `SourceArn:
<distribution>`). That policy is only exercised end-to-end by the Tier 2 `https://${DOMAIN}/...` path.
Don't treat a green Tier 3 as proof the CloudFront path works.

### Phase 6 — User acceptance walkthrough (every UI screen, with wireframes)

**Why this exists.** The curl matrix (Tier 2) proves the chain mechanically; this proves the *product* still
works for a human. The OAC change is invisible when correct — but **every authenticated screen issues an
`/api/v1/...` request that rides CloudFront → OAC → Function URL.** So the walkthrough is simple: open each
screen and confirm it renders real data. A screen that loads = the OAC path works for that call. A screen
stuck spinning / showing an error = the path is broken.

**The key diagnostic for this change (and a masking gotcha).** Two distinct failure signatures:
- **App-level auth** — the client redirects to `/login` on **401** ([`client.ts:54-57`](../../frontend/src/api/client.ts)). A `401` on `/api/v1/*` = simply not logged in (expected pre-login). ✅ auth working.
- **Broken OAC / permission / payload-hash** — the Function URL returns `403`, **but** the distribution's `custom_error_response` rewrites 403→`/index.html` (200) ([cloudfront/main.tf:125-136](../../infra/terraform/modules/cloudfront/main.tf)). So in DevTools → Network you will **not** see a clean `403` on `/api/v1/*`; you'll see **`200` with `Content-Type: text/html`** (the SPA shell) where JSON was expected, and screens break with JSON-parse errors. 🚩 **The tell is HTML where JSON should be — not a 403.** A clean `403` only shows on the **direct** Function-URL test (Security checks below), which bypasses `custom_error_response`.

**Setup.** Run against the **dev** `cloudfront_domain` first (after Phase 5 Tier 2 passes), then repeat on
**prod** after the §7 rollout. Open the site, then open DevTools → Network and keep it visible; optionally
DevTools → Application → Cookies to watch `briefed_session`.

**Step 1 — Onboarding / auth — do this first (most important for this change — exercises the *unauthenticated* `/api/*` path + `Set-Cookie` through the signed origin):**
1. Visit the dev URL with no session → app redirects to **`/login`** (`LoginPage`).
2. Click **"Sign in with Google"** → browser hits `GET /api/v1/oauth/gmail/start?return_to=%2F` → 302 to Google consent (read-only Gmail).
3. Approve consent → Google redirects back to **`/oauth/callback`** (`OAuthCallbackPage`); backend exchanges the code, sets the `briefed_session` cookie, page shows **"Account connected"**, then lands on `/`.
   - ✅ PASS: `briefed_session` cookie is present and you reach the dashboard. This confirms OAC signs the unauthenticated OAuth endpoints **and** CloudFront forwards `Set-Cookie` back through the signed origin.

**Populate data so screens aren't empty.** On the dashboard, use **Scan Now**
([`ScanNowButton.tsx`](../../frontend/src/features/dashboard/ScanNowButton.tsx) → `POST /api/v1/runs`;
desktop button / mobile pull-to-refresh). Wait for the pipeline to finish, then refresh.
> Note: an **empty state is still a PASS** for this change — it means the GET returned `200` with no data,
> which still proves the OAC path. Only HTML-where-JSON-was-expected / error / endless-spinner is a failure.

**Screen gallery — what each screen looks like when it's working.** Happy path only (data present, success
states); these are ASCII approximations of the real components, file refs inline. Walk them in nav order;
each note lists the OAC-path call it rides and what you should see.

**▸ App chrome** — wraps every authenticated screen ([`AppShell.tsx`](../../frontend/src/shell/AppShell.tsx)):
```
DESKTOP (≥ md)                             MOBILE (< md)
┌──────────┬──────────────────────────┐    ┌─────────────────────────┐
│ Briefed  │  <page content>          │    │  <page content>         │
│          │                          │    │                         │
│ 🏠 Home  │                          │    │                         │
│ ⭐ Must… │                          │    │                         │
│ 💼 Jobs  │                          │    ├─────┬─────┬─────┬───────┤
│ 📰 News  │                          │    │ 🏠  │ ⭐  │ 💼  │ ⚙️    │
│ 🧹 Unsub │                          │    │Home │Must │Jobs │Settgs │
│ 📜 Histy │                          │    └─────┴─────┴─────┴───────┘
│ ⚙️ Settgs│                v1.x.x ↘ │      fixed bottom tab bar
└──────────┴──────────────────────────┘
 left sidebar         footer: AppVersion
```

**▸ Login** — `/login` ([`LoginPage.tsx`](../../frontend/src/pages/LoginPage.tsx)):
```
        ┌─────────────────────────────────┐
        │ Welcome to Briefed              │
        │ Sign in with Google to connect  │
        │ your first mailbox. Read-only   │
        │ Gmail; never sends, archives,   │
        │ or unsubscribes on your behalf. │
        │ ┌─────────────────────────────┐ │
        │ │    Continue with Google     │ │
        │ └─────────────────────────────┘ │
        │ By continuing you accept …      │
        └─────────────────────────────────┘
```
→ the button starts `GET /api/v1/oauth/gmail/start?return_to=%2F` → 302 to Google. ✅ you land on Google's consent screen.

**▸ OAuth callback** — `/oauth/callback` ([`OAuthCallbackPage.tsx`](../../frontend/src/pages/OAuthCallbackPage.tsx)):
```
        ┌─────────────────────────────────┐
        │ ✅ Account connected            │
        │ Redirecting to your settings…   │
        └─────────────────────────────────┘
            (auto-redirects in ~1s)
```
→ backend has set the `briefed_session` cookie by now. ✅ cookie present + you reach the app — confirms `Set-Cookie` round-tripped through the signed origin.

**▸ Dashboard** — `/` ([`DashboardPage.tsx`](../../frontend/src/pages/DashboardPage.tsx)):
```
 Today's Digest                      ┌────────────┐
 🟢 Fresh · updated 2m ago           │ 🔄 Scan now│
                                     └────────────┘
 ┌─────────┬───────────┬────────┬──────────────┐
 │MUST READ│GOOD TO RD │ IGNORE │ TODAY'S COST │
 │    4    │    11     │   23   │    $0.06     │
 └─────────┴───────────┴────────┴──────────────┘
 MUST-READ PREVIEW
 ┌─────────────────────────────────────────────┐
 │ Re: Offer — final numbers      [why ▸ 0.92] │
 │ jane@acme.com · you@gmail.com                │
 │ They moved on base + signing; reply by Fri…  │
 │ May 30, 9:14 AM           ↗ Open in Gmail    │
 └─────────────────────────────────────────────┘
```
→ `GET /api/v1/digest/today`; **Scan Now** = `POST /api/v1/runs`. ✅ the four stat tiles + must-read preview render.

**▸ Priority bucket** — `/must-read` · `/good-to-read` · `/ignore` · `/waste` ([`TriagePage.tsx`](../../frontend/src/pages/TriagePage.tsx) + [`EmailCard.tsx`](../../frontend/src/features/email/EmailCard.tsx)):
```
 Must read                               12 total
 🟢 Fresh
 ┌─────────────────────────────────────────────┐
 │ Subject line, truncated…       [why ▸ 0.88] │   ← swipe →
 │ sender@x.com · you@gmail.com                 │    right = Must read
 │ Two-line AI summary excerpt of the body…     │    left  = Ignore
 │ May 30, 8:02 AM           ↗ Open in Gmail    │
 └─────────────────────────────────────────────┘
```
→ `GET /api/v1/emails?bucket=…`; swipe = **WRITE** `PATCH /api/v1/emails/{id}/bucket`. ✅ list renders; a moved email stays moved after reload.

**▸ Jobs** — `/jobs` ([`JobsPage.tsx`](../../frontend/src/pages/JobsPage.tsx)):
```
 Jobs                       [Passed filter] [ All ]
 🟢 Fresh
 ┌─────────────────────────────────────────────┐
 │ Senior Backend Eng — Acme         [  91% ]  │
 │ Remote · USD 180,000–220,000                 │
 │ Matches: Python, AWS, staff-level scope      │
 │ Open posting ↗                               │
 └─────────────────────────────────────────────┘
```
→ `GET /api/v1/jobs?include_filtered=…` (the toggle). ✅ job cards render with a match-score badge.

**▸ News** — `/news` ([`NewsPage.tsx`](../../frontend/src/pages/NewsPage.tsx)):
```
 Tech news digest
 🟢 Fresh
 ┌─────────────────────────────────────────────┐
 │ AI / LLMs                                    │
 │ Markdown summary of the week's clustered     │
 │ newsletters across several sources…          │
 │ Clustered from 6 emails                      │
 └─────────────────────────────────────────────┘
```
→ `GET /api/v1/news`. ✅ newsletter cluster cards render.

**▸ Unsubscribe** — `/unsubscribe` ([`UnsubscribePage.tsx`](../../frontend/src/pages/UnsubscribePage.tsx)). Recommend-only (ADR 0006):
```
 Unsubscribe suggestions
 🟢 Fresh
 ┌─────────────────────────────────────────────┐
 │ news@promo.com                  [score 0.81] │
 │ promo.com                                    │
 │ 0 opens in 60 days across 14 messages.       │
 │ [ Keep ] [ Open unsubscribe link ] [Mark uns]│
 └─────────────────────────────────────────────┘
```
→ `GET /api/v1/unsubscribes`; **WRITE** Keep = `POST …/{id}/dismiss`, Mark = `POST …/{id}/confirm` (records the decision only — never unsubscribes for you). ✅ the row disappears and stays gone after reload.

**▸ Run history** — `/history` ([`HistoryPage.tsx`](../../frontend/src/pages/HistoryPage.tsx)):
```
 Run history
 🟢 Fresh
 ┌─────────────────────────────────────────────┐
 │ May 30, 2026 8:00 AM             [complete]  │  ← click → detail
 │ scheduled                                    │
 │ Ingested 142  Classified 142  Summarized 38  │
 └─────────────────────────────────────────────┘
```
→ `GET /api/v1/history`. ✅ run rows render; your Scan Now run appears with a `complete` badge.

**▸ Run detail** — `/history/:runId` ([`HistoryRunDetailPage.tsx`](../../frontend/src/pages/HistoryRunDetailPage.tsx)):
```
 ← Back to history                      [complete]
 Run a1b2c3d4
 scheduled · started 8:00 AM · finished 8:01 AM
 ┌ Stage timeline ─────────────────────────────┐
 │ Ingested                           [ 142 ]   │
 │ Classified                         [ 142 ]   │
 │ Summarized                         [  38 ]   │
 │ New must-read                      [   4 ]   │
 └──────────────────────────────────────────────┘
 ┌ Cost breakdown ─────────────────────────────┐
 │ LLM spend   $0.06      New must-read   4     │
 └──────────────────────────────────────────────┘
```
→ `GET /api/v1/runs/{id}`. ✅ stage timeline + cost breakdown render.

**▸ Settings shell** — `/settings` redirects to `/settings/accounts` ([`SettingsLayout.tsx`](../../frontend/src/pages/settings/SettingsLayout.tsx)):
```
 Settings
 ┌Accounts┐ Preferences  Prompts  Schedule
 └────────┘─────────────────────────────────────
 <active tab content below>
```

**▸ Settings ▸ Accounts** — `/settings/accounts` ([`AccountsPage.tsx`](../../frontend/src/pages/settings/AccountsPage.tsx) + [`AccountCard.tsx`](../../frontend/src/features/settings/AccountCard.tsx) + [`ProfileSettings.tsx`](../../frontend/src/features/settings/ProfileSettings.tsx)). **The main write surface:**
```
 Gmail accounts                       [+ Add Gmail]
 ┌─────────────────────────────────────────────┐
 │ (Y) you@gmail.com           [ healthy ]      │
 │     Connected May 1 · last sync 8:01 AM      │
 │     142 emails/24h · 6% of daily budget      │
 │     Auto-scan [●—]       [More…] [Disconnect] │
 └─────────────────────────────────────────────┘
 ── Profile ───────────────────────────────────
 Display name      [____________________]
 Email aliases     [alt@x.com, work@x.com ]
 Redaction aliases [____________________]
 ── Schedule ──────────────────────────────────
 Cadence  ( ) Once a day  (•) Twice a day  ( ) Off
 Time slots [08:00] [18:00]   Timezone [US/Eastern ▾]
 Next run: May 31, 2026 8:00 AM
 ── Appearance ──         ── Privacy ──
 ◐ System/Light/Dark        Presidio enabled [—●]
```
→ `GET /api/v1/accounts` + `GET /api/v1/profile/me` + `/profile/me/schedule`. **WRITES:** Auto-scan/More… = `PATCH /accounts/{id}`, Disconnect = `DELETE /accounts/{id}`, Profile fields = `PATCH /profile/me`, cadence/time/tz = `PATCH /profile/me/schedule`, theme/Presidio = `PATCH /profile/me`. **+ Add Gmail** = `GET /api/v1/oauth/gmail/start?link=true…`. ✅ account renders; edits persist on reload; Add Gmail re-runs the OAuth flow.

**▸ Settings ▸ Preferences** — `/settings/preferences` ([`PreferencesPage.tsx`](../../frontend/src/pages/settings/PreferencesPage.tsx)). **The simplest write to test:**
```
 ┌ Automatic daily scans                  [●—] ┐
 ┌ Redact PII before sending to the LLM   [—●] ┐
 ┌ Secure offline mode                    [—●] ┐
```
→ each toggle = **WRITE** `PATCH /api/v1/preferences`. ✅ flip one, reload, it stays flipped.

**▸ Settings ▸ Prompts** — `/settings/prompts` ([`PromptsPage.tsx`](../../frontend/src/pages/settings/PromptsPage.tsx)). Read-only list in 1.0.0:
```
 ┌─────────────────────────────────────────────┐
 │ Recruiter outreach       priority 10 · boost │
 │ { "from_domain": "lever.co", … }             │
 └─────────────────────────────────────────────┘
```
→ `GET /api/v1/rubric`. ✅ the rubric rules render (no save button — editing is post-1.0.0).

**▸ Settings ▸ Schedule** — `/settings/schedule` ([`SchedulePage.tsx`](../../frontend/src/pages/settings/SchedulePage.tsx)). Read-only summary (the editable schedule lives under Accounts ▸ ProfileSettings above):
```
 ┌ Daily digest ───────────────────────────────┐
 │ Sent at 13:00 UTC. Edit via PATCH /preferences│
 │ (UI editor ships in 1.1).                    │
 └─────────────────────────────────────────────┘
 ┌ Retention policy ───────────────────────────┐
 │ { "raw_email_days": 30, "summaries_days":365}│
 └─────────────────────────────────────────────┘
```
→ `GET /api/v1/preferences`. ✅ both cards render.

**Where the writes actually are (1.0.0)** — test at least these so non-GET methods are exercised through CloudFront/OAC (and exercise the Phase 3 `x-amz-content-sha256` path):
- Recategorize an email (swipe) → `PATCH /api/v1/emails/{id}/bucket`
- Toggle a Preference → `PATCH /api/v1/preferences`
- Edit Profile / Schedule / Appearance / Privacy under **Accounts** → `PATCH /api/v1/profile/me` + `/profile/me/schedule`
- Account Auto-scan / Disconnect → `PATCH` / `DELETE /api/v1/accounts/{id}`
- Unsubscribe Keep / Mark → `POST /api/v1/unsubscribes/{id}/dismiss|confirm`
- Read-only in 1.0.0 (no save expected): **Prompts** and **Settings ▸ Schedule**.

> **Offline-queue wrinkle:** recategorize, preference and account writes go through the PWA offline mutation
> queue ([`offline/mutations`](../../frontend/src/offline/)) and update optimistically. Confirm the write
> truly **reached the origin** by reloading — a queued-but-unsynced mutation reverts on reload, which is
> itself a signal the `POST/PATCH` couldn't reach the Lambda.

**Security & negative checks (the actual point of this change, user-observable):**
- 🔒 Paste the raw Function URL in a fresh browser tab (`${FN}health`, or the dev `function_url` output) → **403**. This is the user-visible proof the bypass is closed.
- 🔁 Hard-refresh a deep route (e.g. `/settings/schedule`) → the app still loads (CloudFront SPA fallback; unrelated to OAC but good to confirm it didn't regress).
- 🚪 Log out / clear the `briefed_session` cookie and reload a protected screen → redirected to `/login` (auth still enforced; you'll see a `401`, not a `403`).
- 🧪 Throughout the walkthrough, watch DevTools → Network: `/api/v1/*` responses must be **`application/json`**, never the SPA's `text/html` (the masked-403 signature). Any HTML-where-JSON-was-expected ⇒ stop and fix the OAC/permission/payload-hash before promoting to prod.

**Acceptance criteria (user-level "done"):** every screen in the gallery renders its happy-path content, the
write actions listed above persist across a reload, the OAuth login + an **+ Add Gmail** link both complete,
the raw Function URL returns `403` in a browser, and every `/api/v1/*` response is JSON (no masked HTML).
Run this on **dev**, then re-run the same checklist on **prod** after the §7 rollout.

### Phase 7 — AWS WAF on CloudFront (optional)

**Trade-off to decide before doing this:** WAF adds ~$5–6/mo baseline (web ACL + rules) + per-request
fees, which cuts against ADR 0003's near-zero-cost thesis. For a **portfolio** it's a strong security
signal (rate limiting + AWS managed rule sets + bot control); for a **personal tool** it's arguably
overkill. Recommendation: **document it as a revisit trigger in ADR 0011 and skip for now**, or add a
minimal rate-based rule only. If adopted:

- **`envs/{dev,prod}/main.tf`** — create the ACL with the **`aws.us_east_1`** provider (CLOUDFRONT scope
  must be us-east-1; the alias already exists at `envs/prod/main.tf:27-31`):

```hcl
resource "aws_wafv2_web_acl" "cdn" {
  provider    = aws.us_east_1
  name        = "${var.name_prefix}-cdn-acl"
  scope       = "CLOUDFRONT"
  default_action { allow {} }

  rule {
    name     = "rate-limit"
    priority = 1
    action { block {} }
    statement {
      rate_based_statement { limit = 2000  aggregate_key_type = "IP" }
    }
    visibility_config { sampled_requests_enabled = true  cloudwatch_metrics_enabled = true  metric_name = "rate-limit" }
  }
  rule {
    name     = "aws-common"
    priority = 2
    override_action { count {} }   # start in COUNT mode; flip to none{} after confirming no false positives
    statement {
      managed_rule_group_statement { vendor_name = "AWS"  name = "AWSManagedRulesCommonRuleSet" }
    }
    visibility_config { sampled_requests_enabled = true  cloudwatch_metrics_enabled = true  metric_name = "aws-common" }
  }
  visibility_config { sampled_requests_enabled = true  cloudwatch_metrics_enabled = true  metric_name = "${var.name_prefix}-cdn-acl" }
}
```

- **`modules/cloudfront/main.tf`** — add a `web_acl_arn` variable (default `null`) and set
  `web_acl_id = var.web_acl_arn` on `aws_cloudfront_distribution.this`. Pass
  `web_acl_arn = aws_wafv2_web_acl.cdn.arn` from each env root.

### Phase 8 — Docs

- **`README.md`** — update the front-door description (`:106-107`) to mention OAC + SigV4
  ("CloudFront fronts the Lambda Function URL with Origin Access Control + SigV4 signing; the Function
  URL is `AWS_IAM`-only and not publicly callable"). Fix the stale ADR range "0001–0008" (`:34`, `:127`)
  → "0001–0011". Per CLAUDE.md §5 this is user-visible project state, so it ships in the same change.
- **`docs/adr/README.md`** — add the ADR 0011 row.
- **`backend/app/core/security_headers.py`** — update the `:5-6` comment ("belt-and-braces when CloudFront
  is bypassed"): with OAC the Function URL can no longer be bypassed, so reframe the middleware as
  defense-in-depth for the local/uvicorn runtime, not "bypass" mitigation.

---

## 7. Rollout sequence (prod) — avoid the 403 window

OAC signing and the auth type are independent: if CloudFront signs (OAC `always`) while the Function URL
is still `NONE`, requests still succeed (the signature is ignored). So a **two-step apply** gives
**zero downtime**:

> **Operationalize it — don't hand-comment the auth flip between applies.** Phase 2e wires
> `authorization_type` to `var.function_url_auth_mode` (default `NONE`), with the OAC + both permissions
> created unconditionally. The flip is then a one-line `-var` change, and each step is a reviewable,
> revertible state — no stash/uncomment dance. (Alternatively, ship Step 1 and Step 2 as two separate PRs.)

1. **Step 1 — sign first, keep `NONE`** (`-var function_url_auth_mode=NONE`). Creates the OAC, attaches it to the distribution, and adds **both** `aws_lambda_permission` grants while the Function URL still accepts unsigned calls.
   - Wait for CloudFront propagation (~5–15 min).
   - Verify: `curl -fsS https://<cloudfront_domain>/openapi.json | jq -e '.openapi'` → ok (CloudFront now signs; `NONE` accepts).
     `curl -sf https://<function_url>health` → still 200 (direct access still open at this step).
2. **Step 2 — enforce** (re-apply with `-var function_url_auth_mode=AWS_IAM`) + 2f (CORS removal).
   - Verify: `curl -fsS https://<cloudfront_domain>/openapi.json | jq -e '.openapi'` → ok (signed request accepted).
     `curl -si  https://<function_url>health` → **403** (unsigned direct access now blocked). ✅ success criterion.

**Frontend ordering:** ship Phase 3 (the `x-amz-content-sha256` helper) **before or with** Step 2 — once the
Function URL is `AWS_IAM`, any body-bearing write from a client that doesn't send the hash will `403`.

**dev:** a single combined apply is fine (tolerate a brief 403 during propagation). Do dev fully first,
confirm, then prod.

> Practical note: do prod during a low-traffic window. CloudFront distribution updates propagate
> asynchronously, so even with correct resource ordering there can be a short eventual-consistency window
> on Step 1; the two-step sequence keeps it invisible to users because Step 1 never removes access.

---

## 8. Verification checklist

- [ ] `make tf-validate` passes (dev + prod).
- [ ] `terraform plan` diff matches expectation (new Lambda OAC, distribution update, Function URL auth update, **two** new `aws_lambda_permission` grants, CORS block removed) — and **no** unexpected distribution replace.
- [ ] Frontend `x-amz-content-sha256` helper landed + unit-tested (live client + offline-queue replay).
- [ ] Step 1 applied; `https://<cdn>/openapi.json` returns valid JSON; direct Function URL still 200.
- [ ] Step 2 applied; `https://<cdn>/openapi.json` returns valid JSON; **direct Function URL → 403**.
- [ ] App loads end-to-end through CloudFront; Gmail OAuth login still works (cookie set, session valid).
- [ ] `/api/v1/...` reads work; a body-bearing write (Scan Now `POST`, a Preferences `PATCH`) succeeds (proves the payload-hash path).
- [ ] Both deploy workflows green (smoke step now hits CloudFront with JSON assertion).
- [ ] `make ci` passes locally (includes `tf-validate`, `Makefile:237-265`).
- [ ] ADR 0011 + README + `docs/adr/README.md` updated.

---

## 9. Rollback

- **Fast revert (no infra teardown):** set `-var function_url_auth_mode=NONE` and re-apply — direct access
  and the existing CloudFront path both work immediately. The OAC + permissions can stay harmlessly.
- **Full revert:** `git revert` the change and `terraform apply` (removes OAC, permissions, restores CORS).
- **Deploy-time safety net:** prod's existing auto-rollback (`deploy-prod.yml:276-283`) reverts the Lambda
  alias if the (now CloudFront-based) smoke check fails.

---

## 10. Risks & mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Body-bearing writes `403` after enforcement | Med (if Phase 3 lags) | Ship the `x-amz-content-sha256` helper before/with Step 2 (§7); smoke test asserts a `POST` returns JSON |
| 403 window during cutover | Low | Two-step rollout (§7): sign-first while `NONE`, then enforce |
| Broken OAC masked by `custom_error_response` | Med | Assert JSON (not status) in smoke + Tier 2; UAT diagnostic watches for HTML-where-JSON (§2, Phase 6) |
| Viewer `Authorization` header clobbers SigV4 | Very low | App uses cookies, not `Authorization` (§3); optional 2d-alt custom policy if ever needed |
| `qualifier` mismatch (URL on `live` alias) | Low | Permissions use `qualifier = module.api.alias_name` (= "live"), matching the Function URL's qualifier |
| Provider too old for `lambda` OAC type | None | Pinned `>= 5.50` (needs ≥ 5.41) ✅ |
| WAF cost / false positives (if Phase 7 adopted) | Med | Keep optional; rate-rule first; managed rules in `count` mode before `none` |

---

## 11. Related findings (out of scope — tracked separately)

> Not part of this change. Captured for visibility; do not implement them as part of the OAC work.

### 11.1 SnapStart drift — docs claim SnapStart; all three Lambdas have it disabled

**The contradiction (verified across every Lambda module):**

| Source | Claims |
|---|---|
| ADR 0003 "Decision" | "API Lambda … SnapStart on", "Worker Lambda … SnapStart on", "**No provisioned concurrency. SnapStart carries the cold-start budget.**" |
| ADR 0003 "Consequences" | "SnapStart takes Python cold starts from 1–3 s to **~200–300 ms** post-restore." |
| README.md `:31`, `:106` | advertises "Lambda + **SnapStart**" |
| **`modules/lambda-api/main.tf:125-131`** | "**SnapStart intentionally omitted**: AWS Lambda SnapStart does not support container-image `package_type`… Cold start is therefore Mangum + boto3 + httpx warm-up **~600–900 ms**" |
| `modules/lambda-worker/main.tf:142` | "See lambda-api/main.tf for why SnapStart is intentionally omitted" (also `package_type = "Image"`, `:135`) |
| `modules/lambda-fanout/main.tf` | `package_type = "Image"` (`:106`); **no `snap_start` block at all** |
| `modules/lambda-api/main.tf:2` (same file's own docstring) | still reads "FastAPI via Mangum, **SnapStart on**, Function URL exposed" — contradicts `:125-131` twelve lines down |

**Reality:** all three Lambdas are container-image packaged, and AWS SnapStart does not support
container images — so SnapStart is **off everywhere**, real cold start is **~600–900 ms** (not the
~200–300 ms advertised), and there is no provisioned concurrency to compensate.

**Why it matters (resume context):** this is the single biggest credibility risk in the repo for an
interviewer who reads the ADRs against the code. ADR 0003 is titled "Lambda **+ SnapStart** over Fargate"
and leans on SnapStart as the reason cold starts are acceptable — but the code disproves it, and the API
module's own docstring contradicts its own comment.

**Fix options:**

| Option | What | Trade-off |
|---|---|---|
| **1 (recommended)** | Correct the docs: state SnapStart is unavailable for container-image packaging and document the real ~600–900 ms cold-start budget; fix README `:31`/`:106` and the `lambda-api/main.tf:2` docstring | Low effort, honest. **Constraint:** CLAUDE.md says ADRs are *immutable once accepted* — ADR 0003 is `Status: Accepted`, so this likely needs a **superseding ADR** (e.g. 0012) rather than editing 0003 in place. Confirm the immutability rule before touching 0003. |
| **2** | Move the API Lambda to **ZIP packaging** so SnapStart actually works, restoring ~200–300 ms | Higher effort (build pipeline + dependency layering + the `image_config.command` entrypoint selection would need rework); questionable ROI for a single-user app. The container-image "one image, multiple handlers" simplicity (ADR 0003 Benefits) would be lost. |

**Recommendation:** Option 1 via a superseding ADR + README/docstring fixes. README update is required by
CLAUDE.md §5 (user-visible project state). Tracked separately — out of scope for this change.

### 11.2 ADR index staleness

Root README says "ADRs 0001–0008" (`:34`, `:127`) but 0001–0010 exist today (and 0011 is added by this
plan). **Folded into Phase 8** of this change (cheap, same docs touch).

---

## 12. Interview talking points (why this change pays off)

- *"The Function URL was `NONE`, so I closed the origin bypass with CloudFront OAC and SigV4 signing —
  the 2024 pattern — instead of reaching for API Gateway. For a single tenant behind cookie auth, API
  Gateway's usage plans, authorizers, and throttling bought me nothing OAC didn't, at lower cost. The ADR
  weighs both."*
- Shows depth: I knew OAC over a Lambda URL means the **client** must send `x-amz-content-sha256` on
  body-bearing writes (CloudFront won't hash the body), and that `custom_error_response` masks origin 403s —
  so the smoke test asserts JSON, not status.
- Demonstrates: edge security (SigV4/OAC), least-privilege resource policies (scoped to the distribution
  ARN), zero-downtime cutover reasoning (sign-first/enforce-second), and disciplined trade-off documentation.
- Pair with the genuinely hard parts of the system: the SQS fan-out pipeline (shared DLQ + redrive, per-user
  idempotency lock), the LLM client (fallback → circuit breaker → cost caps), and dual-CMK envelope
  encryption with per-user encryption context.

---

## 13. Estimated effort

| Phase | Effort |
|---|---|
| 1 — ADR 0011 | ~30 min |
| 2 — Terraform (OAC + dual permission + auth-mode var + CORS) | ~1 h |
| 3 — Frontend payload hashing (`x-amz-content-sha256`) + tests | ~3–4 h |
| 4 — CI smoke fix | ~20 min |
| 5 — Local + dev verification | ~30 min |
| 6 — User-acceptance walkthrough | ~30 min |
| 7 — WAF (optional) | ~1 h |
| 8 — Docs | ~20 min |
| Rollout + verify (two-step, incl. propagation waits) | ~1 h |
| **Total (core, no WAF)** | **~6–7 h** |
