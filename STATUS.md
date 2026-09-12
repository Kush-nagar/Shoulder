# Shoulder status

Update this file at every task boundary. Keep it factual and short.

## Supervisor checkpoint

Durable execution state. A fresh session should read this first, then verify it
against Git and GitHub before editing anything.

| Field | Value |
|---|---|
| Last verified `main` | `465b894895383fc6374fd87d569ad60d2830e06f` |
| Completed blocks | Tasks 1–5; Block 01 (Tasks 6–7, PR #8, `ba3b52e`); Block 02 (Tasks 8–10, PR #10, `465b894`) |
| Current block | **Block 03 — Media processing and coach playback** (Tasks 11, 12, 13); not started |
| Current worker / branch | none active |
| Open PRs | none |
| Database revision | `0005_video_ingest` locally and on `Shoulder Dev` |
| Last full verification | 2026-09-10 on `465b894`: repository quality gate green except the Firefox engine (see environment limitations); 286 Python tests; Block 02 gates green on `5f69f9e` |
| Blockers | none that require a human |
| Next action | Start a fresh-context Block 03 worker from `main` at `465b894`; its first job is pinned `ffmpeg`/`ffprobe` tooling and a generated golden fixture, neither of which exists yet |

### Environment limitations on this workstation

- **Firefox browser tests were blocked locally, and are not currently.** Windows
  Smart App Control was enforcing (`VerifiedAndReputablePolicyState = 1`) and
  blocked Mozilla's `lgpllibs.dll`: `LoadLibrary` returned 4551, "An Application
  Control policy has blocked this file," which a clean Playwright reinstall did
  not change. On 2026-09-12 Firefox ran and passed locally — the browser smoke
  suite and the full `tests/player.spec.mjs` matrix — so the block is not
  currently in effect. Nothing here changed Windows policy or the Playwright
  install, so what lifted it is not established; left recorded rather than
  deleted in case it returns. No security policy was disabled, changed, or
  bypassed at any point.
- **`Shoulder Dev` is IPv6-only** (`db.gzbwlancwxhtausyokxt.supabase.co` →
  `2600:1f10:4d85:4400::daa0`). This workstation's IPv6 path to it is
  intermittent; Alembic reached it, and minutes later TCP 5432 did not. Remote
  behavioural suites are retryable when the path is up.
- **Not cloud-portable yet.** `scripts/check.ps1` is cross-platform and needs no
  Docker, but the six other check scripts start the Supabase CLI stack and MinIO
  through Docker. The blocker is Docker-in-sandbox for the Supabase Auth server:
  the magic-link browser suites need a real Auth server, and CI only substitutes
  a bare `postgres` service plus `tests/fixtures/ci-auth-schema.sql`, which
  cannot serve magic links.

## Current state

- Current phase: Phase B — Video. Phase A (Tasks 1–7) is complete and merged.
- Task 1 — Repository, CI, and first deployment: **complete for the owner-authorized local scope** under ADR 0012. Deployment is pending explicit approval.
- Checkout: `D:\Shoulder`, branch `main`; one writer.
- Application: health shell, Task 3 authentication/session boundary, and the Task 4 core identity schema with baseline RLS, separated database roles, and role-aware `/v1/me`.
- Repository: configured origin `Kush-nagar/Shoulder`; owner authorized the Task 1 commit, branch push, and pull request. Repository settings remain unchanged.
- Last verified: 2026-09-08; Task 5 local migration cycle, 75 database tests, 6 auth browser tests and full check passed. Hosted isolation was independently verified. All review verification blockers are resolved; see `docs/task-5-verification.md`.
- Task 2 — Local infrastructure: **complete** under its recorded local scope.
- Task 3 — Verified authentication and session identity: **complete for the owner-authorized local scope**; merged as PR #3. Production-domain acceptance is deferred under ADR 0014.
- Task 4 — Core schema, baseline RLS, and role-aware identity: **complete**, merged as PR #5. Evidence: `docs/task-4-verification.md`.
- Task 5 — Extend the RLS isolation harness: **complete**, merged as PR #6 into `main` at `470dc77`. The development project `Shoulder Dev` runs `0003_roster_display` on PostgreSQL 17. Evidence: `docs/task-5-verification.md`.
- Task 1 PR #1 merged into remote `main` as `198dbc25395f6be4e8da60167a7889c3bd62f5da`, including review repair `2c62d05`; quality and Bugbot passed with all review threads addressed.
- Tasks 1 and 2 are merged; Task 3 started from `76486c5822aa426402945f64be41b9b9c353ab32`. No prior Git history changed.
- The Postgres 17 versus 16 prerequisite is **resolved** and merged as PR #4: [ADR 0015](docs/decisions/0015-postgres-major-version-contract.md) contracts Postgres 17 for local and production, with evidence in `docs/task-4-prerequisite-verification.md`.
- Tasks 1–5 are merged into `main`. From Task 6 onward the repository uses the project-block workflow in `CLAUDE.md`; the roadmap is `docs/projects/README.md`.
- Project Block 1 — Roster and development goals (Tasks 6 and 7): **complete**, merged as PR #8 into `main` at `ba3b52e`. Evidence: `docs/projects/project-01-roster-goals-verification.md`. `Shoulder Dev` runs `0004_roster_goals`. Invitation links an existing account only, under [ADR 0017](docs/decisions/0017-invitation-links-existing-accounts.md).
- Project Block 2 — Video ingest and durable work (Tasks 8, 9, 10): **complete**,
  merged as PR #10 into `main` at `465b894`.
  Evidence: `docs/projects/project-02-video-ingest-durable-work-verification.md`.
  Migration `0005_video_ingest` adds `game`, `video`, `video_upload_part`, and
  `processing_job` with RLS, plus the `shoulder_worker` runtime role under
  [ADR 0018](docs/decisions/0018-worker-database-role.md). `Shoulder Dev` now runs
  **`0005_video_ingest`**: 9 tables, 11 `private` functions, 34 policies, forced RLS
  on all 9, zero `anon`/`authenticated`/`PUBLIC` grants, and column grants matching
  the contract. Remote behavioural suites could not run on that pass because the
  project host is IPv6-only and this workstation's IPv6 path to it went down after
  the migration; the gap and its retry procedure are recorded in the verification
  record. The private R2 bucket and its CORS list still need an owner-selected
  production origin before any deployment.
- The block was requested as "Task 9 durable job table, Task 10 ffmpeg → HLS". That
  contradicts `docs/06-tasks.md` (Task 9 is the resumable upload UI, Task 10 is the
  durable queue, transcode is Task 11) and HLS is forbidden by `AGENTS.md` rule 8 and
  ADR 0001. The conflict was raised before implementation and the owner chose the
  repository-canonical scope. No ADR was overturned and nothing in the block
  transcodes.

## Task 3 local implementation

- Next.js magic-link request, PKCE callback, neutral signed-in page, proxy refresh,
  sign-out, and same-origin identity BFF. `/v1/me` remains reserved for Task 4.
- Supabase SSR `getClaims()` plus live Auth session checks; no trust in the
  `getSession()` user object, browser IDs, or editable role metadata.
- FastAPI independently validates asymmetric JWKS signatures, issuer, audience,
  expiry, subject/session UUIDs, and live session existence. Copied cookies and
  tokens fail after sign-out; no product permissions are inferred.
- HttpOnly, host-only, SameSite=Lax cookies; Secure for HTTPS; explicit loopback
  HTTP development exception. Fixed redirects, origin/host checks, no-store
  responses, and suppressed development callback query logging.
- Dependencies pinned: SSR 0.12.6, Supabase JS 2.115.0, server-only 0.0.1,
  PyJWT[crypto] 2.13.0. Lockfile changes are limited to their dependency graphs.
- Final `scripts/check-auth.ps1`: all six real Chromium/Firefox/WebKit auth tests
  passed, including expired-token refresh, copied-cookie/token rejection after
  logout, replay, and rate-limited resend survival. No tests skipped or weakened.
- Final `scripts/check.ps1`: Biome, TypeScript, five Node policy/repository tests,
  Ruff, strict mypy, nine Python tests, generated contracts, production build,
  browser-secret bundle scan, and three health-shell browser tests passed.
- Dependency audits and `git diff --check` passed. Final cleanup left zero Auth
  users and no `app` schema; all containers stopped and `docker ps` was empty.
  Docker's recurring stale socket startup issue was repaired without resetting
  data; Desktop 4.90.0 was observed after continuation, not installed by this run.
- Exact commands, repairs, security review, file inventory, and limitations:
  `docs/task-3-verification.md`.
- Deployment, production-domain/callback configuration, and production auth
  verification remain deferred. Task 3 PR handoff is authorized; no merge or Task 4 work.
- PR #3 merge-gate review repaired missing no-store headers on Auth HTTP/network
  outages and missing configuration. Regression tests cover all three paths.
  The BFF field-growth suggestion is deferred: the current FastAPI response model
  already enforces the identity-only contract. Merge is authorized after checks pass.

## Task 2 completed work and verification

- Added local CLI bootstrap, Supabase configuration, digest-pinned MinIO Compose,
  local lifecycle/recovery scripts, and a credential-free root `.env.example`.
- CLI **2.116.0**, official GitHub release Windows amd64 zip, SHA256
  `d88832770615c915e1782af99ba6475afcfdc026f939214940f7eea9aaa2341e`;
  installed only in ignored `.tools/supabase`. Needed to own local Auth/Postgres.
- Docker Desktop **4.89.0**, installed with winget from Docker's official
  `https://desktop.docker.com/win/main/amd64/238018/Docker%20Desktop%20Installer.exe`,
  verified installer SHA256 `854626704af28a160d5af68b96b3e32eacf08ab397ce6c12eb02a04788d73681`.
  Includes Docker CLI/Engine **29.7.2**, Compose **5.5.0**; required for the
  documented Linux containers. No cloud account or resource created.
- WSL **2.7.13.0**, kernel **6.18.33.2-2**, now available after the owner's host
  setup. Microsoft WSL is Docker's Linux container backend; all development
  commands and repository files remain Windows-native in `D:\Shoulder`.
  Source: `https://learn.microsoft.com/en-us/windows/wsl/install`.
- Initial CPU flags suggested disabled virtualization; `HypervisorPresent=True`
  contradicted that interpretation. Docker logs established the actual blocker
  was missing WSL. It is resolved; `docker info` returns **29.7.2**.
- ADR 0013 records the CLI's explicit rejection of Postgres 16 and the local
  Postgres **17.6.1.165** image. ADR 0015 supersedes its production 16 target:
  Supabase has no 16 major, so local and production both contract Postgres 17.
- Bootstrap/checksum, generated TOML parsing via `supabase services`, Compose
  validation, PowerShell parsing, and destructive-check opt-in rejection passed.
- Task 1 check found missing `.mjs` LF policy after branch checkout; added it to
  `.gitattributes` and normalized four files with Biome; no logical application
  changes. The full regression rerun passed.
- `scripts/check-infra.ps1 -DiscardLocalData` passed both in the canonical
  checkout and a fresh local clone with the uncommitted source overlaid, fresh
  CLI installation, and fresh local credentials. Implementation hashes matched.
  Verified idempotent bootstrap/start/migrate, health, pinned images, loopback
  ports, denied anonymous reads, restart persistence, interruption/recovery,
  and empty reset. Final database check returned zero Auth users and no `app` schema.
- `scripts/check.ps1` passed all checks: Biome format/lint, TypeScript, two
  repository/font tests, Ruff format/lint, strict mypy, API unittest, generated
  contract drift, production build, three browser tests, and `git diff --check`.
- `pnpm audit --audit-level=low` and `uv run --locked pip-audit` passed with no
  known vulnerabilities. Full commands and failures/repairs are recorded in
  `docs/task-2-verification.md`.
- Windows initially blocked Ruff 0.16.6. Its executable matched the official
  release checksum. On 2026-09-06 the same executable was allowed under the
  unchanged Windows policy; version, format, lint, and full regression passed.
  No security policy was disabled, changed, or bypassed.
- Docker's stale socket startup error was repaired by preserving its two
  socket-only runtime directories under backup names, then restarting. No
  factory reset occurred. Docker's native localhost-default binding is enabled;
  its previous settings are backed up. Details are in the verification record.
- Local services are stopped; Docker remains available. Ports on start: 54321,
  54322, 54324, 9000, 9001. Start: `scripts/infra.ps1 start`; stop preserves data;
  reset/recovery tests require explicit `-DiscardLocalData` and affect only
  Shoulder local volumes. No external account or approval blocker remains for Task 2.
- Source and diff review found no secrets, product data, widened authorization,
  or unintended source files. Task 3 and all later functionality remain absent.
- No application dependencies, schema, RLS, product routes, or real data added.

## Completed work

- PR #1 review repairs: reusable SVG accessible names no longer depend on fixed
  IDs; Fly's Dockerfile path resolves relative to `infra/fly.toml`. Full local
  quality checks and the config-path assertion passed. Hosted quality and Bugbot
  passed before merge; deployment remains pending approval.

- Documentation reconciliation and font prerequisite update are complete.
- Task 1 has web/API/worker/contracts/infra boundaries, exact dependency pins and lockfiles, environment examples, secret-file exclusions, generated health contracts, and pull-request CI.
- The owner-approved mark and wordmark in `assets/brand/` validate and render as inline currentColor SVG components. No geometry or approved typography was changed.
- `@fontsource-variable/inter-tight` resolved version **5.3.0** is pinned in `apps/web/package.json` and `pnpm-lock.yaml`. WOFF2 assets are self-hosted with `next/font/local`; no runtime Google Fonts request. The included SIL Open Font License is preserved verbatim in `apps/web/public/licenses/inter-tight-OFL.txt`.
- Local web and API `/health` both return HTTP 200 with `{"status":"ok"}`.
- Task 1 added no database, migrations, authentication, RLS implementation, storage, jobs, video, CV, or sample player data. Task 2 adds only the local infrastructure documented above.

## Toolchain decisions

- Existing Windows-native Node **24.11.1**, npm **11.6.2**; no system-wide installation.
- pnpm **11.25.0**, selected explicitly through `npm.cmd exec --yes --package=pnpm@11.25.0 -- pnpm`; not a Codex-only binary.
- uv **0.12.10**, official GitHub Windows archive with verified SHA256, in ignored `.tools/`.
- CPython **3.11.16**, installed by uv into ignored `.tools/python/`; environment in `.venv/`, uv cache in `.cache/uv/`.
- CI uses the same pinned versions; Vercel may use a newer managed Node 24 patch.
- ADR: `docs/decisions/0012-task-1-local-acceptance.md`. Exact dependency versions, rationale, failures, and repairs: `docs/task-1-verification.md`.

## Verification

All of these passed. Exact commands and individual outcomes, including diagnostic
failures and reruns, are recorded in `docs/task-1-verification.md`.

- `.\scripts\bootstrap.ps1`: pinned tooling, `uv sync --locked`, `pnpm install --frozen-lockfile`, and browser install.
- README commands: `npm.cmd exec --yes --package=pnpm@11.25.0 -- pnpm dev:web` and `.\.tools\uv.exe run --locked python -m uvicorn services.api.main:app --host 127.0.0.1 --port 8000`; both `Invoke-RestMethod` health checks returned ok; shell returned 200.
- `.\scripts\check.ps1`: Biome format/lint, TypeScript, two Node repository/font tests, Ruff format/lint, strict mypy, Python API test, deterministic generated-contract drift check, production build, three browser smoke projects, and `git diff --check`.
- `npm.cmd exec --yes --package=pnpm@11.25.0 -- pnpm audit --audit-level=low` and `.\.tools\uv.exe run --locked pip-audit`: no known vulnerabilities.
- `pnpm licenses list --json`: dependency license inventory reviewed; included font license retained.
- Chromium, Firefox, WebKit: health, original SVG paths/viewBoxes, same-origin WOFF2, weights 400/500/600, license response, no page errors, axe checks; 27 screenshots across nine sizes. 320px and 1440px screenshots visually inspected.
- Final source/diff inspection: no secret values, product data, authorization surface, or out-of-scope implementation; secret-bearing local files ignored. No tests skipped or weakened.

## Remaining approval and operational inputs

| Input / work | Needed by | State |
|---|---|---|
| Explicit deployment approval, Vercel/Fly targets, region, accounts/access | Public deployment | Pending; config prepared in `infra/`; nothing deployed |
| Hosted pull-request CI | Final Task 1 evidence | Passed on PR #1, including its review repairs; merged |
| Repository visibility | Before external publication/real-data use | Unverified and unchanged; owner authorized local Task 1 scope |
| Additional approved SVG variants / raster derivatives | Before their placements ship | Two Task 1 sources supplied; other placements deferred |
| Production domains | Before production auth acceptance/deployment | Owner choice outstanding; localhost Task 3 is authorized |
| Coach/organization footage permission and participant notice | Before real footage or minors' data anywhere | Owner confirmation required |
| Season end timestamp, shared-footage erasure policy, responsible deletion/incident operator, actual provider backup expiry at most 30 days | Before real-data onboarding / Task 22 gate | Owner confirmation required under ADR 0009 |

## Known limitations

- Hosted Task 1 CI passed. CI is configured on pull_request and runs the shared local quality script; each later PR must pass its own checks.
- Vercel/Fly configuration is prepared; Docker image execution, public endpoints, and real-phone deployment checks are unverified until approval/access.
- Browser engines on Windows are not evidence of tests on physical iOS/Android devices.
- Task 3 adds neutral authentication controls only; product isolation, drafts, media, and CV load-bearing tests remain later-task work and are not claimed complete.
- Remaining product, retention, privacy, and CV decisions stay governed by `docs/00-decisions.md` and ADRs 0001–0011.

Recommended next local command: `.\scripts\infra.ps1 start`.

## Project Block 2 local implementation

- Task 8: `app.game`, `app.video`, `app.video_upload_part` with forced RLS and
  column-level write grants; `services/api/storage.py` wrapping pinned `boto3` for
  multipart start/sign/list/complete/abort, object existence, and object-specific
  signed GET; nine coach routes in `services/api/video.py`. Object keys are
  `originals/{video_id}/source.{ext}` derived from the generated id and a three-entry
  extension allowlist, never from a submitted filename. Parts are reconciled from
  `ListParts`, never claimed by the client.
- Task 9: `/coach/upload` with match creation, file validation, three concurrent part
  PUTs straight to storage, `localStorage` resume hints, server-authoritative
  reconciliation, reselect-the-same-file recovery, and the exact `docs/05-ui.md`
  tab-closure copy. Five same-origin BFF routes, each naming one fixed upstream path.
- Task 10: `app.processing_job` with idempotency keys, `FOR UPDATE SKIP LOCKED`
  claims, leases, heartbeats, exponential backoff to a five-minute ceiling,
  cooperative cancellation, bounded terminal failure, and a stale-lease sweeper;
  `services/worker/` runs it as a separate process with no HTTP surface. No
  production handler ships in this block, so enqueued rows wait for Tasks 11 and 12
  rather than burning attempts.
- Three review passes (implementer, independent reviewer, and the pull request's
  automated reviewers, across four rounds) produced 21 findings; all are fixed or explicitly
  accepted, with regression tests, in the verification record. The load-bearing ones
  were a rolled-back rejection state, a shutdown that recorded an in-flight job as
  cancelled, a completion race that reported 503 for an upload that succeeded, and a
  botocore exception chain that could have carried an object key into a worker log.
- Proofs: a 2 GB file through the real multipart path in 13 s over 64 parts; two
  workers claiming 100 jobs with no double execution, stable across three runs; a
  browser upload interrupted, reloaded, reselected, and resumed without repeating a
  completed part, on Chromium, Firefox, and WebKit.
- `boto3` 1.43.91 is the one new production dependency; the rationale is recorded in
  `docs/projects/project-02-video-ingest-durable-work.md`.
- No ML, CV, scoring, ranking, comparison, parent surface, or player-facing text was
  added. No existing test was skipped or weakened; `tests/roster.spec.mjs` extended its
  fixture truncation list because `app.game` now references `app.team`.

## Independent Task 4 review

- Fixed revoked-player access, restricted bootstrap to a separate operator role, and removed role/grant artifacts on base downgrade; ADR 0016 records the operator boundary.
- The previous linked-development blocker is resolved by the `Shoulder Dev` deployment, which is the development project for all later work.
- Independent verification: 38 real Supabase DB tests and 38 exact-image CI-fixture tests passed; up/down/up and role cleanup passed; 6 real auth browser tests and the full check passed.
- Final delta review: confirmed Shoulder Dev revision and remote role separation read-only; strengthened the local-version guard regression and corrected superseded deployment-blocked statements.
- Final delta checks: four repository tests, disabled-guard mutation check, full `check.ps1`, and `git diff --check` passed.
