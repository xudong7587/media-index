# MediaIndex Agent Guide

## Delivery Model

`Latest GitHub release -> local browser development and acceptance -> user says “发布 Git” -> PR / CI / main / GitHub release -> user manually updates MediaIndex-public on NAS`

- Local browser sandbox is the only development, testing, and manual acceptance environment.
- GitHub is the only publication channel.
- `MediaIndex-public` on NAS is the user's manually updated real-use version. Do not deploy, modify, diagnose, or test it unless the user explicitly starts a separate NAS task.
- Do not use `-test`, `-dev`, or `-local` version suffixes. A locally accepted version becomes the matching GitHub release version.

## New Session: Minimal Context

Read only this file and `docs/LOCAL_TESTING.md` before an ordinary task. Read a domain document only when the task touches that domain. Do not scan the repository, inspect infrastructure, or run broad tests without a concrete reason.

State one lane in one sentence, then implement:

| Lane | Use for | Default proof |
| --- | --- | --- |
| L0 | Copy, small UI, narrow local logic fix | Read call sites; at most one focused test |
| L1 | Local browser behavior or user-facing feature | L0 plus local browser acceptance |
| B | Transfers, tracking, paths, DB, auth, security, providers, notifications, scheduler | Relevant regression test and boundary review |
| R | User explicitly says `发布 Git` / `发布 GitHub` | Release checks, PR, CI, merge `main`, GitHub release |

## Local Sandbox

The persistent local test environment is documented in `docs/LOCAL_TESTING.md`.

- Start or reuse it with `.\scripts\start-local.ps1`.
- Frontend: `http://127.0.0.1:5173/`; backend: `http://127.0.0.1:8000/openapi.json`.
- Its ignored `.tmp/local-055/` directory contains user-managed configuration, database, cache, and logs. Never commit, reset, or overwrite it.
- Keep real side effects disabled by default. When the user deliberately configures real QAS, 115, TMDB, or notifications there, describe the external action before triggering it.
- The local enterprise-WeChat simulator runs the normal command logic against the local configuration and captures replies instead of sending them to enterprise WeChat. It does not validate a real callback.
- The local enterprise-WeChat simulator is a debug-only, uncommitted overlay. Keep its code out of every R release; before staging a release, explicitly verify that no simulator routes, UI, styles, or tests are included.

## Product Boundaries

- Prefer `needs_review` over an uncertain transfer, rename, path, provider, or completion claim.
- Backend owns paths, identity, matching, provider selection, and execution. Frontend displays, selects, and confirms.
- Provider failures must not hide or undo other provider results.
- `api/` adapts HTTP; `services/` owns workflows; `providers/` adapt clouds; `clients/` call external systems; `db/` owns persistence; `domain/` has no HTTP, DB, or client dependency.
- New UI belongs in `frontend/src/features/<domain>/` or `components/`, not as more feature code in legacy `frontend/src/main.tsx`.
- Never expose credentials or alter user data without explicit instruction.

## Tests

Do not invent test-point counts. Each test protects a concrete regression or observable contract.

- L0: no build or full suite by default; explain when no focused test is needed.
- L1: use the local browser and run a frontend build only when it provides useful compilation proof.
- B: add or update a regression test and run related tests.
- Run the full backend suite only for shared contracts, migrations, providers, scheduler/concurrency, auth/security, or R.
- Never weaken assertions, skip tests, or use `|| true` to make checks pass.

## GitHub Release

Do not create a PR, push, merge, build a release, or change the release version until the user explicitly says `发布 Git` or `发布 GitHub`.

At R: preserve the locally accepted code, run release-appropriate checks, commit intentionally, open/complete the PR and CI flow, merge `main`, and let GitHub build the public image and release. The user then updates `MediaIndex-public` manually.

## Final Report

Keep it short: lane, behavior changed, focused proof, local URL and acceptance item, and what was not done.
