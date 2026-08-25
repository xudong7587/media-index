# Module Boundaries and Regression Strategy

## Purpose

The product is valuable only when a new capability cannot silently change where media is saved, what is renamed, which provider acts, or what an existing task means. The primary design rule is therefore isolation before reuse: share stable contracts, not route handlers or provider internals.

## Dependency Direction

```text
frontend -> API -> services -> domain
                    |       ^
                    v       |
                 providers -> clients
                    |
                    v
                   db
```

`api` adapts HTTP and delegates. `services` owns workflows. `providers` implement the shared transfer contract. `clients` call remote systems. `db` persists state and migrations. `domain` must remain independent of HTTP, SQLite, and external clients.

The architecture check prevents new service-to-API imports. Two WECOM callback imports are an explicit legacy exception, not a pattern to copy. When WECOM command behavior changes materially, extract its transfer/review calls into a shared service first and remove the exception.

## Feature Ownership

| Domain | Backend owner | Frontend owner | Protected contracts |
| --- | --- | --- | --- |
| Discovery and matching | `services/*resolver*`, `episode_matcher`, `movie_matcher` | `features/discover` | TMDB identity, evidence threshold, review fallback |
| Transfer execution | `transfer_service_v2`, `providers/` | `features/discover`, `features/history` | provider isolation, path generation, rename plan, terminal status |
| Review | `api/review.py` until workflow extraction | `features/review` | approved candidate cannot cross provider; superseded candidates cannot execute |
| Tracking and wishlist | `tracking_engine_v2`, `wishlist_engine`, `scheduler` | `features/tracking`, `features/wishlist` | no historical backfill during automatic tracking; one active task per media/season/provider |
| External sync | `openlist_sync` | `features/settings/openlist` | sync only missing files; no duplicate active sync |
| Notifications and WECOM | `notifications`, `notification_channels`, `wecom_callback` | `features/notifications`, `features/settings/notifications` | notification is downstream of persisted state; callbacks are authenticated and deduplicated |
| STRM inventory and cleanup | `cloud_inventory`, `strm_jobs`, `strm_reconciler`, `deletion_workflow` | `features/strm` | incremental jobs never clean; full cleanup is root-scoped, twice-confirmed, fused, and exact-path only |
| MDC-NG integration | `api/mdc_webhook.py`, `scheduler` | `features/integrations` | token authenticated; request body cannot widen saved scope; finished events coalesce into incremental jobs |
| Settings and security | `core/config`, `core/security`, `api/config.py` | `features/settings` | secrets remain server-side; config update does not erase unrelated values |

`frontend/src/main.tsx` currently contains legacy UI composition. It is intentionally capped by the architecture test. New features must live in a feature folder; take the smallest related component out of `main.tsx` when wiring the feature.

## Change Rules

1. Change only the owning domain plus its public contract. Do not repair unrelated code while adding a feature.
2. Keep provider-neutral orchestration separate from QAS, P115, MoviePilot, OpenList, and notification implementation details.
3. Database changes are additive first. Preserve old rows, backfill deliberately, and test migration from the prior schema.
4. A background job must persist a useful state before external work and must have a terminal or recoverable outcome after a restart.
5. Cross-domain behavior requires a contract test at the boundary, not a large test count.

## Required Regression Tests by Risk

| Change | Minimum proof |
| --- | --- |
| Matching, parsing, naming, or paths | table-driven edge case that would otherwise transfer/rename incorrectly |
| Provider or transfer state | independent success/failure and duplicate-execution test |
| Database schema or migration | old-schema upgrade test plus affected query test |
| Scheduler or background job | restart/retry/idempotency test |
| Auth, callback, secrets, or configuration | authorization/redaction/invalid-input test |
| UI-only change | focused component behavior when practical; build only when the user needs rendered NAS output |

## Adversarial Review Baseline (2026-08-04)

- Verified: API routes, service workflows, providers/clients, SQLite persistence, and scheduler are distinct directories; provider-specific transfer implementations share a protocol.
- Verified: the full pytest suite and frontend production build are the required local/CI gates. CI must invoke pytest directly; `unittest discover` does not collect every pytest-style test module.
- Risk accepted and quarantined: `services/wecom_callback.py` imports internal transfer/review route helpers. It must not gain further API dependencies.
- Risk accepted and reduced: `frontend/src/main.tsx` remains a legacy composition file capped at 3,888 lines by an architecture test. Shared settings UI and discovery primitives have been extracted; new UI code must continue moving into `features/` instead of raising the cap.
- Pending: browser-level end-to-end coverage for the core transfer/review path. Add it only with a stable local test fixture; do not substitute a large brittle suite now.
