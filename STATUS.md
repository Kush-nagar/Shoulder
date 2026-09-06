# Shoulder status

Update this file at every task boundary. Keep it factual and short.

## Current state

- Current phase: Phase A — Foundation.
- Task 1 — Repository, CI, and first deployment: **complete for the owner-authorized local scope** under ADR 0012. Deployment is pending explicit approval.
- Checkout: `D:\Shoulder`, branch `task-1-foundation`; one writer.
- Application: minimal Next.js health shell and FastAPI health only.
- Repository: configured origin `Kush-nagar/Shoulder`; owner authorized the Task 1 commit, branch push, and pull request. Repository settings remain unchanged.
- Last verified: 2026-09-06.
- Next task: Task 2 — Local infrastructure; not started or authorized by this task.

## Completed work

- PR #1 review repairs: reusable SVG accessible names no longer depend on fixed
  IDs; Fly's Dockerfile path resolves relative to `infra/fly.toml`. Full local
  quality checks and the config-path assertion passed. Hosted checks are required
  before the owner-authorized merge; deployment remains pending approval.

- Documentation reconciliation and font prerequisite update are complete.
- Task 1 has web/API/worker/contracts/infra boundaries, exact dependency pins and lockfiles, environment examples, secret-file exclusions, generated health contracts, and pull-request CI.
- The owner-approved mark and wordmark in `assets/brand/` validate and render as inline currentColor SVG components. No geometry or approved typography was changed.
- `@fontsource-variable/inter-tight` resolved version **5.3.0** is pinned in `apps/web/package.json` and `pnpm-lock.yaml`. WOFF2 assets are self-hosted with `next/font/local`; no runtime Google Fonts request. The included SIL Open Font License is preserved verbatim in `apps/web/public/licenses/inter-tight-OFL.txt`.
- Local web and API `/health` both return HTTP 200 with `{"status":"ok"}`.
- No database, migrations, authentication, RLS implementation, storage, jobs, video, CV, or sample player data was added.

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
| Hosted pull-request CI | Final Task 1 evidence | Commit/push/PR authorized; await the created PR checks |
| Repository visibility | Before external publication/real-data use | Unverified and unchanged; owner authorized local Task 1 scope |
| Additional approved SVG variants / raster derivatives | Before their placements ship | Two Task 1 sources supplied; other placements deferred |
| Production domains | Before Task 3 auth callback/cookie setup | Owner choice outstanding |
| Coach/organization footage permission and participant notice | Before real footage or minors' data anywhere | Owner confirmation required |
| Season end timestamp, shared-footage erasure policy, responsible deletion/incident operator, actual provider backup expiry at most 30 days | Before real-data onboarding / Task 22 gate | Owner confirmation required under ADR 0009 |

## Known limitations

- Hosted CI will run after the authorized branch push and pull request. CI is configured on pull_request and runs the shared local quality script.
- Vercel/Fly configuration is prepared; Docker image execution, public endpoints, and real-phone deployment checks are unverified until approval/access.
- Browser engines on Windows are not evidence of tests on physical iOS/Android devices.
- The shell has no controls or product states; later-task auth, isolation, drafts, media, and CV load-bearing tests are not applicable yet and are not claimed complete.
- Remaining product, retention, privacy, and CV decisions stay governed by `docs/00-decisions.md` and ADRs 0001–0011.

Recommended next local command: `.\scripts\check.ps1`.
