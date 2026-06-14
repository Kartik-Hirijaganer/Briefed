# Google OAuth verification runbook

Phase 13 operator checklist for moving Briefed from a test-user Gmail path to a
verified production OAuth app.

## Decision gate

Do not enable public Connect Gmail until all of these are complete:

- Custom domain ownership is verified in Google Search Console.
- `briefed.email` is added as an OAuth authorized domain.
- OAuth branding, policy links, redirect URI, and scopes match the values below.
- Google OAuth verification is approved.
- CASA security assessment is complete and accepted.

Until then, keep the OAuth app in Testing, keep production Gmail connect disabled,
and direct recruiters to the synthetic demo.

## Required values

| Field | Value |
|---|---|
| Authorized domain | `briefed.email` |
| Homepage | `https://briefed.email/` |
| Privacy Policy | `https://briefed.email/privacy` |
| Terms of Service | `https://briefed.email/terms` |
| Redirect URI | `https://briefed.email/api/v1/oauth/gmail/callback` |
| Public base URL | `BRIEFED_PUBLIC_BASE_URL=https://briefed.email` |
| Frontend connect flag | `VITE_ENABLE_GMAIL_CONNECT` unset or not `true` until approval |

## Scopes

The OAuth consent screen scopes must exactly match the runtime request:

| Scope | Purpose shown in policy |
|---|---|
| `https://www.googleapis.com/auth/gmail.readonly` | Ingest Gmail message metadata and content for triage and summaries. |
| `https://www.googleapis.com/auth/gmail.modify` | Mark selected Gmail messages as read only after a user action. |
| `https://www.googleapis.com/auth/userinfo.email` | Identify the connected Google account email. |
| `https://www.googleapis.com/auth/userinfo.profile` | Identify the connected Google account profile. |
| `openid` | Bind the Google identity to the Briefed session. |

If any scope changes, update the Privacy Policy, Terms, frontend login copy, and
Google scope justification before submitting.

## Console steps

1. Verify `briefed.email` in Google Search Console with the same Google account
   that owns or edits the Cloud project.
2. In Google Cloud Console, open Google Auth Platform -> Branding and add:
   homepage `https://briefed.email/`, privacy `https://briefed.email/privacy`,
   and terms `https://briefed.email/terms`.
3. Add `briefed.email` under Authorized domains.
4. In Google Auth Platform -> Data Access, add only the scopes listed above and
   write scope justifications that match the policy purposes.
5. In Credentials, open the Web OAuth client and add the redirect URI
   `https://briefed.email/api/v1/oauth/gmail/callback`.
6. Confirm the deployed backend setting is
   `BRIEFED_PUBLIC_BASE_URL=https://briefed.email`; otherwise the OAuth start
   endpoint will generate a redirect URI that does not match the client.
7. Add test users while the app remains in Testing.
8. Record and attach a consent-flow demo video showing:
   homepage -> Connect Gmail -> login disclosure checkbox -> Google consent
   screen with the listed scopes -> callback to `/app` -> legal consent gate.
9. Submit OAuth verification.
10. Complete CASA security assessment before enabling Connect Gmail for public
    production users.

## Verification checks

Run these before submitting and again before enabling public Gmail connect:

```bash
curl -I https://briefed.email/
curl -I https://briefed.email/privacy
curl -I https://briefed.email/terms
curl -I https://briefed.email/api/v1/health
```

Then start OAuth from a test-user browser session and confirm the Google
authorize URL includes:

- `redirect_uri=https%3A%2F%2Fbriefed.email%2Fapi%2Fv1%2Foauth%2Fgmail%2Fcallback`
- exactly the five scopes listed above
- no `briefed.vercel.app`, CloudFront, localhost, or stale preview domain

## References

- [Google verification requirements](https://support.google.com/cloud/answer/13464321)
- [Configure the OAuth consent screen and scopes](https://developers.google.com/workspace/guides/configure-oauth-consent)
- [OAuth app branding and authorized domains](https://support.google.com/cloud/answer/15549049)
- [Unverified app behavior](https://support.google.com/cloud/answer/7454865)
