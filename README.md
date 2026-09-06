# Shoulder

Shoulder is a private, coach-led soccer development tool. A coach gives one player one active development goal, marks three to six moments from a match, writes one sentence about each moment, and publishes player-only clips. The player watches on a phone and may write a reflection.

Computer vision is optional and deferred. When it is introduced, it may nominate moments for a coach to inspect. It never judges a player, produces a score, or writes text a player can see.

## Start here

Read in this order:

1. `AGENTS.md`
2. `STATUS.md`
3. `docs/01-product.md`
4. The current task in `docs/06-tasks.md`
5. Only the task-specific references named by that task

Claude Code loads `CLAUDE.md`, which imports `AGENTS.md`. Codex loads `AGENTS.md` directly. The two tools therefore receive the same canonical rules.

## Document map

| File | Purpose |
|---|---|
| `AGENTS.md` | Non-negotiable engineering and product rules |
| `CLAUDE.md` | Claude Code adapter; imports `AGENTS.md` |
| `STATUS.md` | Current task, completed work, decisions, and blockers |
| `PROMPTS.md` | Copy-ready prompts and the two-agent workflow |
| `docs/00-decisions.md` | Resolved contradictions and architecture decisions |
| `docs/01-product.md` | Product definition, users, loop, and scope |
| `docs/02-architecture.md` | System boundaries, data flow, deployment, and storage |
| `docs/03-schema.md` | Database contract and RLS access matrix |
| `docs/04-api.md` | HTTP contract and authorization rules |
| `docs/05-ui.md` | Screen-level behavior and copy requirements |
| `docs/06-tasks.md` | Ordered implementation plan and gates |
| `docs/07-cv.md` | Deferred offline computer-vision plan |
| `docs/08-brand.md` | Brand rules and asset requirements |
| `docs/09-frontend-design-system.md` | Detailed visual, responsive, component, and interaction specification |
| `docs/10-security-privacy.md` | Threat model, minor-safety controls, retention, and deletion |
| `docs/11-testing-quality.md` | Test strategy, performance budgets, and release gates |
| `docs/12-agent-workflow.md` | Codex/Claude Code comparison, setup, handoffs, and conflict rules |
| `docs/13-licenses-and-sources.md` | External-code boundaries and research sources |
| `docs/decisions/` | Focused architecture decision records |
| `assets/` | Supplied brand reference and production-asset requirements |

## Task 1 local foundation

The repository contains only the health shell and API, generated health contracts,
a reserved worker boundary, CI, and deployment preparation. No authentication,
database, storage, jobs, video processing, or player data is implemented.
Deployment is pending explicit approval; see `infra/README.md` and `STATUS.md`.

## Windows-native setup

Use PowerShell in `D:\Shoulder` with Git and **Node.js 24.11.1**. Node is an
ordinary Windows installation, not a Codex runtime dependency. If needed, obtain
that version from [Node's official release](https://nodejs.org/download/release/v24.11.1/).
No global pnpm, Python, uv, Docker, or WSL installation is required for Task 1.

```powershell
Set-Location D:\Shoulder
.\scripts\bootstrap.ps1
```

The bootstrap downloads checksum-verified uv 0.12.10 into ignored `.tools/`,
installs CPython 3.11.16 locally, installs locked Python dependencies into
`.venv/`, and uses explicit `pnpm@11.25.0` through `npm.cmd exec` to install
the frozen workspace lockfile and browser test binaries. `npm.cmd` avoids
PowerShell npm-launcher policy issues. No secrets or .env file are needed.

Run the web in one PowerShell terminal:

```powershell
Set-Location D:\Shoulder
npm.cmd exec --yes --package=pnpm@11.25.0 -- pnpm dev:web
```

Run the API in a second terminal:

```powershell
Set-Location D:\Shoulder
.\.tools\uv.exe run --locked python -m uvicorn services.api.main:app --host 127.0.0.1 --port 8000
```

Open [the local shell](http://127.0.0.1:3000). Both health routes must return HTTP
200 with `{"status":"ok"}`:

```powershell
Invoke-RestMethod http://127.0.0.1:3000/health
Invoke-RestMethod http://127.0.0.1:8000/health
```

Stop each server with Ctrl+C before running the full check (which owns ports 3000
and 8000 and starts production-mode servers itself):

```powershell
.\scripts\check.ps1
```

This checks Biome format/lint, TypeScript, repository/secret-file/font checks,
Ruff format/lint, mypy, Python tests, generated-contract drift, the Next.js
production build, and browser health/font/SVG/accessibility smoke tests.
Screenshots and failure traces go into ignored `test-results/`.

Dependency checks (also in CI):

```powershell
npm.cmd exec --yes --package=pnpm@11.25.0 -- pnpm audit --audit-level=low
.\.tools\uv.exe run --locked pip-audit
```

Inter Tight **5.3.0** is self-hosted from Fontsource; its included SIL Open Font
License ships with the web app. See `assets/README.md` for exact source and
license paths. Both SVGs render inline with their original vector geometry.

## Repository boundaries

| Path | Task 1 responsibility |
|---|---|
| `apps/web/` | Next.js App Router health shell and /health |
| `services/api/` | FastAPI /health and OpenAPI |
| `services/worker/` | Documented boundary only; no running worker |
| `packages/contracts/` | Generated OpenAPI and TypeScript contract |
| `infra/` | Vercel/Fly deployment instructions and API configuration |
| `scripts/` | Windows bootstrap, shared local/CI checks, contract export |
| `tests/` | Repository checks, API tests, browser smoke |
| `.github/workflows/ci.yml` | Pull-request quality checks; no deployment |

Exact direct dependency versions and every verification command/result are in
`docs/task-1-verification.md`.

## Task 2 local infrastructure

Task 2 infrastructure and regression verification passed on 2026-09-06.
Task 3 is next; it has not been started. See `docs/task-2-verification.md` for
the full command record, host repairs, and compatibility limits.

Keep the repository and PowerShell on Windows. Containers use Docker Desktop's
WSL 2 backend; a Linux development checkout is unnecessary. The verified tool
versions are Docker Desktop **4.89.0**, Docker **29.7.2**, Compose **5.5.0**,
WSL **2.7.13.0**, and project-local Supabase CLI **2.116.0**.

On a machine without WSL, run `wsl --install --no-distribution` in administrator
PowerShell and restart if requested. Install the pinned Docker Desktop from
the official installer via winget:

```powershell
winget install --id Docker.DockerDesktop --exact --version 4.89.0 --source winget
```

Start Docker Desktop. In **Settings > Resources > Network**, select
**Localhost by default** for **Port binding behavior**, then apply the change.
The setup refuses to start with the broad default. This changes the default
for containers on this Docker Desktop installation; explicitly published
addresses still take precedence. No Docker or Supabase account is required.

From a clean checkout on this configured host:

```powershell
Set-Location D:\Shoulder
.\scripts\bootstrap-infra.ps1
.\scripts\infra.ps1 start
.\scripts\infra.ps1 health
.\scripts\infra.ps1 migrate
.\scripts\infra.ps1 stop
```

Bootstrap verifies the CLI archive against its pinned SHA256 and generates
random MinIO credentials once in ignored `.env.local`. `.env.example` contains
no usable password. Do not copy cloud secrets into local setup. The CLI's
state stays under ignored `.tools/supabase-home`; generated project state is
ignored by `supabase/.gitignore`. Startup output suppresses local credentials.

Supabase owns the only Postgres and local Auth containers, plus Kong and captured
mail. Realtime, Studio, Data API, Supabase Storage, analytics, and edge runtime
are excluded. MinIO is the private S3-compatible storage boundary in Compose.
Its `shoulder-local` bucket denies anonymous reads. Images are pinned by digest
in `infra/supabase-images.json` and `infra/compose.yaml`.

The CLI rejects Postgres 16. Local Postgres **17.6.1.165** is documented in
[ADR 0013](docs/decisions/0013-local-supabase-postgres-version.md); production
version compatibility must be resolved before Task 4. There are no application
migrations in Task 2: `migrate` runs the CLI's explicit local migration command
with no product SQL. Product schema changes will use Alembic in their assigned tasks.

| Local service | Address |
|---|---|
| Auth gateway | `http://127.0.0.1:54321/auth/v1/health` |
| Postgres | `127.0.0.1:54322` |
| Captured mail UI | `http://127.0.0.1:54324` |
| MinIO S3 | `http://127.0.0.1:9000` |
| MinIO console | `http://127.0.0.1:9001` |

Stop preserves local volumes. Reset deletes **only Shoulder local database and
MinIO volumes** and recreates empty services; it never contacts a linked cloud
project. The recovery suite also discards those local volumes:

```powershell
.\scripts\infra.ps1 reset -DiscardLocalData
.\scripts\check-infra.ps1 -DiscardLocalData
.\scripts\check.ps1
```

The infrastructure suite checks repeatable start/migrate, health, denied anonymous
object access, synthetic-object persistence over restart, interrupted storage
detection and recovery, and empty storage after reset. Use synthetic fixtures
only. To leave no services running, use `.\scripts\infra.ps1 stop`.

If Docker reports it cannot rename `engine.sock` or `sailor-ingest.sock`, preserve
images and volumes; do not factory-reset Docker. This host encountered Docker's
stale AF_UNIX socket issue. Stop Docker fully before investigating its runtime
socket directories. Recovery details and verification evidence are in
`docs/task-2-verification.md`.

## Product boundary in one sentence

The software retrieves evidence; the coach decides what it means.
