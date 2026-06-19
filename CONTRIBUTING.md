# Contributing to Scheduler

Thanks for your interest in contributing! Scheduler is the open core of an
open-source shift-scheduling platform (a Go API, a Next.js web app, native
mobile clients, and a billing-free scheduling engine), licensed under
**AGPL-3.0**. This guide explains how to propose changes.

By participating in this project you agree to abide by our
[Code of Conduct](CODE_OF_CONDUCT.md).

## Before You Start

- **Open an issue first for anything substantial.** For bug fixes that are small
  and obvious, a direct pull request is fine. For new features, behavior
  changes, or refactors, please **open an issue first** so we can agree on the
  approach before you invest time. This is the "issue-first" rule for big
  changes.
- **Security issues are different.** Do **not** open a public issue or PR for a
  vulnerability — follow [SECURITY.md](SECURITY.md) instead.

## Development Workflow

1. **Fork** the repository and create a topic branch from `main`
   (e.g. `fix/schedule-overlap` or `feat/byo-billing-stripe`).
2. **Make focused changes.** Keep each pull request scoped to a single concern.
   Smaller, focused PRs are reviewed and merged faster than large mixed ones.
3. **Build and test** the parts of the monorepo you touched, following the
   instructions in the [README](README.md) and the per-app READMEs:
   - **API** (`services/api`): `make test && make build`
   - **Web** (`apps/web`): `npm ci`, then `npm run typecheck`, `npm run lint`,
     `npm run test`, and `npm run build`
   - **Engine** (`packages/core`): run its tests as documented in the package.
   CI (`.github/workflows/ci.yml`) runs these same checks on every PR, so a
   green local run means a green CI run.
4. **Open a pull request** using the
   [pull request template](.github/PULL_REQUEST_TEMPLATE.md) and fill in every
   section. Link the issue your PR addresses.

## Sign Your Work (Developer Certificate of Origin)

Contributions are accepted under **AGPL-3.0** via the
[Developer Certificate of Origin](https://developercertificate.org/) (DCO).
The DCO is a lightweight way for you to certify that you wrote the patch, or
otherwise have the right to submit it under the project's license.

To certify your work, **sign off** every commit:

```sh
git commit -s -m "fix: correct overlap detection in schedule engine"
```

The `-s` flag appends a `Signed-off-by:` trailer with your name and email — the
same identity as your Git author. By signing off you agree to the terms of the
DCO at <https://developercertificate.org/>.

> A CLA may be introduced later; until then contributions are under AGPL-3.0 via
> DCO.

If you forgot to sign off your last commit, amend it:

```sh
git commit --amend -s --no-edit
```

## Review and Merge

- A maintainer will review your PR. Please respond to review feedback and keep
  the branch up to date with `main`.
- All status checks must pass and your commits must be signed off (DCO) before a
  PR can be merged.

## Reporting Bugs and Requesting Features

Use the issue templates:

- **Bug report** — [`.github/ISSUE_TEMPLATE/bug_report.md`](.github/ISSUE_TEMPLATE/bug_report.md)
- **Feature request** — [`.github/ISSUE_TEMPLATE/feature_request.md`](.github/ISSUE_TEMPLATE/feature_request.md)

Thank you for contributing!
