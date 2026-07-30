# MediaIndex Agent Guide

MediaIndex is a personal NAS media discovery, transfer, tracking, sync, and notification console. Prefer `needs_review` over any uncertain transfer, rename, path, provider, or completion claim.

## Non-Negotiable Delivery Line

`GitHub Release -> self-use NAS branch and manual acceptance -> user says “发布 Git” -> GitHub image/release -> MediaIndex-public display check`

- The current clean baseline is public release `0.5.3` (`357e207`). Every feature begins from the current public release, never an old NAS folder or abandoned worktree.
- The self-use NAS is the only development, daily-use, and manual acceptance environment.
- `MediaIndex-public` only opens the published image for a final visual check. Never develop, modify files, or run workflow tests there.
- Do not create `-test`, `-dev`, or `-local` versions. A self-use accepted version and its later GitHub release share one formal version number.

## New Session: Minimal Read

Read this file, `docs/DEVELOPMENT_FLOW.md`, and `docs/LOCAL_DEPLOYMENT.md`. Do not scan the full repository, run full tests, build Docker, inspect unrelated code, or touch GitHub for a narrow fix.

State one lane in one sentence, then implement:

| Lane | Scope | Default proof |
| --- | --- | --- |
| A0 | Local copy/text/narrow logic fix | Relevant call site and at most one focused test |
| A1 | Self-use backend patch | A0 plus SCP changed files and `reload backend` |
| A2 | Self-use frontend change | Build only when the user wants to see the page, SCP `frontend/dist`, then `reload frontend` |
| B | Transfer, tracking, paths, DB, auth, security, providers, notifications, scheduler | Relevant regression test and domain-boundary review |
| C | User explicitly says `发布 Git` / `发布 GitHub` | PR, CI, merge `main`, GitHub release/image |

## Module and Safety Boundaries

- The backend owns paths, media identity, file matching, rename plans, provider selection, and execution decisions. The frontend only displays, selects, and confirms.
- Provider jobs are independent. A provider failure cannot hide or roll back another provider's success.
- `api/` adapts HTTP; `services/` owns workflows; `providers/` adapt clouds; `clients/` call external systems; `db/` owns persistence; `domain/` has no HTTP, DB, or client dependency.
- New UI belongs in `frontend/src/features/<domain>/` or `components/`, never as more code in legacy `frontend/src/main.tsx`.
- Never expose secrets, alter `data/` or `downloads/`, or discard user changes without explicit instruction.

## Tests

Do not invent test-point counts. Each test must protect a concrete regression or contract.

- A0: no build and no full suite. Explain if no focused automated test is needed.
- B: add/update a regression test when behavior crosses a module boundary; run the relevant tests.
- Full backend tests are for shared contracts, migration, provider, scheduler/concurrency, auth/security, or C.
- A frontend build only proves compilation. Run it for A2/C/dependency changes or when the user needs rendered self-use output.
- Never weaken assertions, add broad mocks, skip tests, or use `|| true` to pass checks.

```powershell
$env:PYTHONPATH = 'backend'; python -m unittest tests.test_name
$env:PYTHONPATH = 'backend'; python -m unittest discover -s tests
pnpm --dir frontend build
```

## Self-Use NAS: SCP and Reload Only

`docs/LOCAL_DEPLOYMENT.md` is the only authority for NAS address, SSH key, staging path, container name, and current readiness.

- **Current verified fact (2026-07-30):** SCP staging is ready at version `0.5.3`; `media-index-nas` uses `mediaindex-scp`; the SFTP upload root is `/docker/media-index`. For A1/A2, proceed with SCP and reload. Do not repeat the baseline reset or block deployment by checking `/volume2/...` through SSH.
- The deployment account intentionally has no general remote shell. A failed `test`, `ls`, or other arbitrary SSH command is an access-control result, not evidence that staging files are absent.
- Primary deployment channel is **SSH/SCP**, not WebDAV. Do not use, repair, or wait for WebDAV.
- Upload only changed source files to the documented SCP staging tree. Never upload source archives, run compose, pull GHCR, or build Docker for A1/A2.
- Then run exactly one restricted command: `ssh -o BatchMode=yes media-index-nas "sudo -n /usr/local/sbin/media-index-reload <backend|frontend|all|status>"`.
- The deployment user has no saved sudo password, no Docker group, no remote shell, and no arbitrary sudo. It can only SCP files and invoke those four reload modes.
- Do not claim deployment from upload alone: report `container updated` only after reload and a narrow page/API smoke check.
- Only reconsider staging readiness if the user explicitly says the NAS/staging directory was replaced or deleted. Otherwise treat the verified state above as authoritative.

## GitHub Release

Manual acceptance on the self-use NAS is the product gate. A PR is the GitHub record used to merge accepted code; CI is GitHub's automated test/build guard and does not replace manual acceptance.

Only after the user says `发布 Git` / `发布 GitHub`: create the PR, wait for CI, merge `main`, publish the same formal version, and let GitHub Actions/GHCR build the image. Never build the public image on the NAS.

## Final Report

Keep it short: lane, changed behavior, tests, self-use state (`local only` / `SCP uploaded` / `container updated`), what the user should inspect, and what was not done.
