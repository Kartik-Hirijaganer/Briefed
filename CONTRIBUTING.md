# Contributing to Briefed

Thanks for your interest. Briefed is a single-maintainer OSS project, so
the contribution loop is small and informal — but the quality bar is real.

## Ground rules

1. **No surprise PRs.** Open an issue first for anything beyond a small
   bug fix or doc typo. Drive-by refactors are almost always rejected.
2. **Follow the coding standards in [CLAUDE.md](CLAUDE.md).** Python +
   TypeScript both have enforced linters, formatters, and docstring
   conventions. CI will reject anything that doesn't pass.
3. **Architectural decisions land as ADRs** in `docs/adr/` before the code
   lands. If a PR would change a decision captured in an ADR, open the new
   ADR in the same PR.
4. **One PR = one concern.** Split formatting-only commits from behavior
   changes. `fix:` + `refactor:` + `docs:` don't all belong together.

## Local setup

Prereqs: Python 3.11+, Node 20+, Docker, Make.

```bash
git clone https://github.com/Kartik-Hirijaganer/Briefed.git
cd Briefed
cp .env.example .env        # fill in only what you need
make bootstrap              # installs Python + Node deps, starts services
make dev                    # backend on :8000, frontend on :5173
```

## Running tests

```bash
make test          # unit + integration (Python + frontend)
make lint          # formatter + linter + type-check
make coverage      # 80% line-coverage gate (+ listed 100% modules)
make e2e           # Playwright (slow; needs PLAYWRIGHT=1)
make eval          # Promptfoo prompt evals (needs EVAL=1)
make link-check    # Verify markdown links across README + docs/**
```

CI runs the same Make targets, so passing locally means passing in CI —
no environment drift.

## Branching + commits

- Work on feature branches off `main`; never push directly to `main`.
- Conventional Commits: `feat:`, `fix:`, `refactor:`, `docs:`, `chore:`,
  `test:`, `build:`, `ci:`.
- Sign commits (`git config user.signingkey`, `commit.gpgsign=true`) for
  anything that lands on `main`.

## Pull requests

- Fill in the PR template.
- Linked CI checks must pass: `lint`, `test`, `coverage`, `docs-drift`
  (includes `make link-check`), `security`, `terraform` (validates dev
  + prod envs).
- If you change a user-visible command, env var, or setup step, update
  the root [README.md](README.md) in the same PR (CLAUDE.md §5).
- Add a `[Unreleased]` entry to [CHANGELOG.md](CHANGELOG.md).

## Security

Please do not file public issues for security problems. See
[docs/security/SECURITY.md](docs/security/SECURITY.md) for the disclosure
process.

## Releases

Cutting a tag is a release-engineer task — see
[`docs/release/v1.0.0.md`](docs/release/v1.0.0.md) for the
1.0.0 cut and [`docs/operations/rollback.md`](docs/operations/rollback.md)
for the rehearsal we run before every prod tag. The
[`deploy-prod`](.github/workflows/deploy-prod.yml) workflow performs
the blue/green alias swing and writes the audit row in
`release_metadata`.

## License

By contributing, you agree your contributions are licensed under the
same [MIT License](LICENSE) that covers the rest of the project.
