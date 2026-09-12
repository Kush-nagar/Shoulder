# Task 2 verification record

Task 2, `D:\Shoulder`, branch `task-2-local-infrastructure`; one writer.
Initial implementation was completed without a commit or push. The owner later
authorized final verification, a Task 2 commit, branch push, and a PR into `main`.
The owner subsequently authorized merging Tasks 1 and 2 after all checks and
reviews pass, synchronizing `main`, and preparing an empty Task 3 branch.
Deployment, cloud resources, and Task 3 implementation remain unauthorized.
Status: **passed**, 2026-09-06. Canonical and fresh-clone infrastructure recovery,
the complete regression suite, dependency audits, and final scope checks passed.
The initial Windows Ruff block resolved under the unchanged security policy.

## Prerequisite and scope

`git switch main`, `git pull --ff-only origin main`, `git status --short`,
`git branch -avv`, `git log main..task-1-foundation --oneline`: initially Task 1
was not merged. On the owner's subsequent authorization,
`git merge --ff-only task-1-foundation` advanced local main from `83c346c` to
`053311a`; `git switch -c task-2-local-infrastructure` created this branch.
Remote main was not pushed. Task 1 local acceptance follows ADR 0012.

Read the requested root instructions and numbered documents, including the
exact Task 2 prerequisite and architecture. Added no application authentication,
product schema, migration SQL, RLS, product routes, media pipeline, or ML.

## Tools and immutable sources

| Tool/image | Exact version/source | Result/reason |
|---|---|---|
| Supabase CLI | `2.116.0`, official GitHub release Windows amd64 zip; bootstrap pins SHA256 | Installed in `.tools/supabase`; owns local Auth/Postgres |
| Docker Desktop | `4.89.0`, official Docker installer through winget | Installed; required Linux containers |
| Docker CLI/Engine | `29.7.2` | `docker --version` and `docker info` verified |
| Docker Compose | `5.5.0` | `docker compose version` verified |
| WSL | `2.7.13.0`, kernel `6.18.33.2-2`, Microsoft WSL | Owner installed host prerequisite; Windows-native repo retained |
| Supabase Postgres | `17.6.1.165` | Local-only ADR 0013; CLI rejects major version 16 |
| Supabase Auth | `v2.196.0` | Required local identity infrastructure only |
| Supabase Kong | `2.8.1` | Required Auth gateway |
| Supabase Mailpit | `v1.30.2` | Captures local mail; no external SMTP |
| MinIO | `RELEASE.2025-09-07T16-13-09Z` | Required private S3-compatible boundary |
| MinIO client | `RELEASE.2025-08-13T08-35-41Z` | Transient bucket setup and synthetic verification |

The four Supabase image digests are in `infra/supabase-images.json`; MinIO
digests are in `infra/compose.yaml`. Startup resolves only locked images, tags
them for the CLI, and checks the running Supabase image IDs against the lock.
No new npm or Python application dependency was added.

Amended 2026-09-12 (Block 03): both MinIO references now name MinIO's own
`quay.io` registry instead of Docker Hub, because anonymous Docker Hub pulls of
these images began failing from shared CI egress. The releases and digests above
are unchanged -- `quay.io` serves the identical manifest lists -- so this changed
where the bytes come from, not which bytes.

Docker installer URL, checksum, and exact installed tool versions are also
recorded in `STATUS.md`. Supabase's archive SHA256 is verified before extraction.
Public registry manifest requests established MinIO digests; Docker's first
official ECR pulls established Supabase digests.

## Command/check results

| Command/check | Result |
|---|---|
| `Get-Command docker,wsl,supabase` and Docker path inspection | Docker/CLI initially absent; WSL stub present |
| `wsl --help`, `wsl --status`, `wsl --version` | Initially missing WSL; later verified WSL 2 ready |
| `Get-CimInstance Win32_OperatingSystem`, `Win32_Processor`, `Win32_ComputerSystem` | Windows 11 Home build 26200; hypervisor running. CPU flags initially misinterpreted; corrected before BIOS changes |
| `Get-WindowsOptionalFeature -Online ...` | Required actual Windows elevation; no feature changes made by that check |
| Official Supabase release/changelog and source reads via `Invoke-RestMethod`/`Invoke-WebRequest` | Verified CLI version, command source, image versions, config, network behavior, CLI home override |
| `supabase --version`, `--help`, `init --help`, `start --help`, `services --help`, `db --help`, `stop --help`, `db reset --help`, `migration up --help`, `telemetry --help` | Verified actual pinned command surface |
| `supabase init` | Generated config; pared down to required local services |
| `supabase services` with major 16 | Printed `Invalid db.major_version: 16`; command misleadingly returned zero. Explicitly treated as unsupported, not success |
| `supabase services` with major 17 | Parsed config and resolved expected versions |
| `supabase telemetry disable` | Passed; project bootstrap scopes CLI state to `.tools/supabase-home` |
| `winget show --id Docker.DockerDesktop --exact --source winget --accept-source-agreements` | Official installer metadata verified |
| `winget install --id Docker.DockerDesktop --exact --version 4.89.0 --source winget --silent --accept-package-agreements --accept-source-agreements --disable-interactivity` | Installer hash verified; installation passed |
| `docker --version`, `docker compose version`, `docker info --format '{{.ServerVersion}}'` | Exact versions above; initial missing-engine failure resolved after WSL setup |
| `scripts/bootstrap-infra.ps1` | Passed; checksum verification and random ignored credentials |
| PowerShell AST parsing of the three infrastructure scripts | Passed |
| `docker compose --env-file .env.local -f infra/compose.yaml config --quiet` | Passed; no interpolated credentials printed |
| `scripts/check-infra.ps1` without discard switch | Correctly rejected destructive suite before service mutation |
| `scripts/infra.ps1 health` before engine ready | Correctly failed at Docker connectivity |
| `scripts/infra.ps1 start` | Initially caught broad Supabase bindings; stopped Supabase. Native Desktop localhost setting fixed host exposure; verifier corrected to accept IPv6 `::1` |
| `docker ps`, targeted `docker inspect`, `docker network inspect`, `Get-NetTCPConnection -State Listen` | Final observed bindings were IPv4/IPv6 loopback only; one Postgres |
| `scripts/check-infra.ps1 -DiscardLocalData` | Passed: start, repeated start, local migrate, anonymous object denial, stop/start persistence, kill/recover MinIO, empty reset |
| `scripts/check.ps1` first run | Failed on four `.mjs` CRLF files after Git checkout |
| `pnpm format` via pinned npm exec | Normalized four files; `.gitattributes` now pins `.mjs` LF; no logical application changes |
| `scripts/check.ps1` second run | Biome format/lint, TypeScript, two repository/font tests passed; stopped at Windows Application Control blocking Ruff |
| `uv run --locked ruff --version` on 2026-09-06 | Same verified binary now allowed under unchanged policy; returned `ruff 0.16.6` |
| `scripts/check.ps1` final run | Passed every stage, including Ruff format/lint, mypy, API test, deterministic contracts, production build, three browsers, and whitespace check |
| `uv run --locked mypy` | Passed: four source files |
| `uv run --locked python -m unittest discover -s tests -p 'test_*.py'` | Passed: one API test |
| `uv run --locked python -m scripts.export_openapi`; `pnpm contracts` | Passed; Git diff confirms no generated-contract drift |
| `pnpm build` | Passed Next.js production build |
| `pnpm smoke` | Passed Chromium, Firefox, WebKit: three tests, responsive/font/SVG/accessibility checks |
| `pnpm audit --audit-level=low`; `uv run --locked pip-audit` | Passed: no known vulnerabilities |
| `git diff --check`; `git check-ignore .env.local .tools/supabase-home/telemetry.json supabase/.temp/cli-latest` | Passed; generated state and credentials ignored |

All `pnpm` commands above use
`npm.cmd exec --yes --package=pnpm@11.25.0 -- pnpm`; `uv` is `./.tools/uv.exe`.
Initial sandbox Git writes and CLI user-state writes were denied, then used
authorized escalation. One format/check dispatch was rejected by automatic
approval review's usage limit and did not execute; later authorized calls worked.

## Docker Desktop socket recovery

The screenshot's error was independently confirmed in Docker's host log:
its own stale AF_UNIX socket could not be renamed. This matches the upstream
[Docker issue](https://github.com/docker/desktop-feedback/issues/554).

`docker desktop stop --force --timeout 30` stopped the failed app. Verified no
Docker backend/UI process remained, and inspected the exact runtime directories.
`Remove-Item` on `engine.sock` and `fsutil reparsepoint query` failed with Windows
error 1920. No factory reset or image/volume deletion was used for this repair.

Renamed socket-only directories with PowerShell `Rename-Item` after verifying
their resolved absolute paths and contents:

- `%LOCALAPPDATA%/docker-secrets-engine` to
  `docker-secrets-engine.shoulder-stale-20260905` (only `engine.sock`).
- `%LOCALAPPDATA%/Docker/run` to `run.shoulder-stale-20260905`
  (only `dockerInference` and `sailor-ingest.sock`).

`docker desktop start --timeout 45` then passed. Backups remain outside Git.
Docker's `settings-store.json.shoulder-backup` also preserves its previous
configuration. The sole intended setting change was `PortBindingBehavior` to
`default-local-port-binding`, verified in Docker's own settings log and Windows
TCP listeners. This installation-wide default makes implicit published ports
local-only; explicit host addresses are still honored.

## Resolved Windows lint blocker

`uv run --locked ruff format --check .` was blocked by Windows Smart App Control,
error 4551, policy `{0283ac0f-fff1-49ae-ada1-8a933130cad6}`. The subsequent
`ruff check .` was initially unrun. CodeIntegrity event log and registry policy state
confirmed enforcement; no policy was weakened or bypassed.

Installed Ruff **0.16.6** executable SHA256:
`6302914e8dd8bd64e911710476d9b4634a8a052ec9a25e5d2c72400b43f51a4c`.
Its package RECORD and checksum-verified official GitHub Windows release match.
The release zip SHA256 is
`d968cbf82bcb42042a59e9478a48f9a00db88cceaa2eeaa86c4834c02a70eaf6`.
An initial checksum comparison used an undecoded binary HTTP response and failed;
reading the saved official checksum text confirmed the archive matched.
Both executable copies are unsigned. The second copy was inspected, not executed.

The owner authorized trusting Ruff. However, Microsoft documents that Smart App
Control offers no per-app approval; no narrow exception could be applied.
See [Microsoft's FAQ](https://support.microsoft.com/en-us/windows/security/threat-malware-protection/smart-app-control-frequently-asked-questions).
On 2026-09-06 the same executable successfully returned its version under the
unchanged policy. The full regression rerun then passed: Ruff reported four
files already formatted and no lint errors. No alternate executable or policy
bypass was used. The reason Windows changed its verdict is not established.

## Fresh checkout reproduction and final review

Created `.tools/task-2-clean` with
`git clone --no-hardlinks --no-local --single-branch --branch task-2-local-infrastructure . .tools/task-2-clean`.
Because commits are prohibited, overlaid only `git ls-files --modified --others
--exclude-standard` source files. No ignored dependencies, caches, `.env.local`,
or generated CLI state were copied. Compared SHA256 of all three infrastructure
scripts, Compose, Supabase config, and image lock against canonical source: identical.

Ran `.tools/task-2-clean/scripts/check-infra.ps1 -DiscardLocalData` using its
own freshly downloaded CLI and generated credentials. It passed all checks,
including repeated bootstrap without credential overwrite and repeated migrate.
The first clone-run process handle was lost between turns; after confirming no
check remained active, reran with durable output in `.tools/infra-clean-verification.log`.
The observed final run exited zero and printed the complete PASS summary.

The full canonical `scripts/check.ps1` exited zero, with durable output in
`.tools/task-2-regression.log`. Both logs are ignored local artifacts. Final
`pnpm format:check`, `pnpm lint`, Node repository/secret/font tests, PowerShell
parsing, Compose `config --quiet`, ignore checks, and `git diff --check` passed.
No tests were skipped, weakened, or marked expected-failure. PowerShell used
for verification was the existing **7.6.5** installation.

`docker exec supabase_db_shoulder-local psql -U postgres -d postgres -At -v
ON_ERROR_STOP=1 -c "SELECT count(*) FROM auth.users; SELECT to_regnamespace('app')
IS NULL;"` returned `0` and `t` after reset. Stopped the clone's services with
its `scripts/infra.ps1 stop`. Docker image cache and empty data volumes remain.

Final changed source files: `.gitattributes`, `README.md`, `STATUS.md`.
Added: `.env.example`, `infra/compose.yaml`, `infra/supabase-images.json`,
`scripts/bootstrap-infra.ps1`, `scripts/infra.ps1`, `scripts/check-infra.ps1`,
`supabase/.gitignore`, `supabase/config.toml`, ADR 0013, and this record.
Four `.mjs` files were physically normalized after checkout; Git content diff
and `git diff --ignore-space-at-eol` show no logical changes to those files.
Reviewed for credentials, privacy, authorization, deletion scope, and unintended
files. No product schema or API changes.

## Final pre-commit validation — 2026-09-06

- `git branch --show-current`: `task-2-local-infrastructure`.
- `scripts/infra.ps1 start`: passed. `Get-NetTCPConnection -State Listen`
  confirmed 54321/54322/54324 on `127.0.0.1` and `::1`, and 9000/9001 on
  `127.0.0.1`. `scripts/infra.ps1 stop`: passed.
- `scripts/check.ps1`: exited zero; all format/lint/type/unit/contract/build
  checks and all three browser tests passed. Log: `.tools/task-2-final-check.log`.
- `scripts/check-infra.ps1 -DiscardLocalData`: exited zero; all recovery checks
  passed. Log: `.tools/task-2-final-infra.log`. Stopped services again afterward;
  `docker ps --format '{{.Names}}'` returned no running containers.
- Both dependency audits passed with no known vulnerabilities. PowerShell AST
  parsing, Compose `config --quiet`, ignore checks, repository secret scan,
  and `git diff --check` passed. The generated local password is absent from
  all tracked/new source files; its value was not printed.
- Full tracked diff and every new source file reviewed. The four `.mjs` files
  have zero Git content diff and need no entries in the Task 2 commit. No Task 3
  work, product data, credentials, generated state, or machine state is included.
- `git ls-remote origin refs/heads/main` returned `83c346c`; the requested PR
  into `main` also carries existing Task 1 commit `053311a`. The new commit is
  limited to Task 2. Remote `main` is not modified by this handoff.
- The owner authorized commit message `Complete Task 2 local infrastructure`
  and PR title `Task 2: Local infrastructure and Supabase`. The final handoff
  reports the resulting SHA, PR URL, and observed hosted check status.

## PR #2 review and prerequisite integration — 2026-09-06

- Task 1 PR #1 merged as `198dbc25395f6be4e8da60167a7889c3bd62f5da` after
  quality and Bugbot passed. Its repair `2c62d05` fixed reusable SVG title IDs
  and the Fly config-relative Dockerfile path on the Task 1 branch.
- Merged `origin/main` into the published Task 2 branch without rebasing or
  force-pushing. Resolved only a `STATUS.md` conflict, preserving both task records.
  The resulting diff against `origin/main` contains only the original 13 Task 2
  files; Task 1 repairs and the four unchanged `.mjs` files are absent from that diff.
- Copilot's duplicate SVG finding is addressed by the Task 1 repair. Its Docker
  base-image digest suggestion concerns the deferred Task 1 deployment scaffold,
  now outside this PR; no dependency upgrade is required for Task 2.
- The claimed UTF-16 `Set-Content` defect did not reproduce. Native Windows
  PowerShell 5.1 wrote synthetic `KEY=ascii` as bytes
  `4B-45-59-3D-61-73-63-69-69-0D-0A`, without a BOM or UTF-16 null bytes.
  Generated usernames and hexadecimal passwords are entirely ASCII, so the
  existing encoding is compatible with Compose in both 5.1 and PowerShell 7.
- No change to the secret scan: there is no observed binary false positive,
  and skipping extensions would weaken the existing check. Its UTF-8 decoding
  retains recognizable ASCII credential patterns and the suite passes.
- No Task 2 runtime repair was needed. Infrastructure scripts and pinned
  configuration remain identical to the passing final recovery run above.
  The combined branch's `scripts/check.ps1` exited zero before its integration
  commit, including all three browser tests; log: `.tools/task-2-review-check.log`.
  `git diff --check`, ignore checks, and the original-13-file scope review passed.
  Hosted checks and a final merged-main rerun gate the final handoff.

## Local data and cleanup

Only a fixed, non-identifying infrastructure text object is used by the recovery
suite; reset removes it. Ports: 54321 Auth, 54322 Postgres, 54324 captured mail,
9000 MinIO, 9001 console. Web/API regressions temporarily use 3000/8000.
`scripts/infra.ps1 stop` preserves volumes and stops services;
`scripts/infra.ps1 reset -DiscardLocalData` deletes/recreates only Shoulder local
volumes. No external account is needed for Task 2. Task 3 remains unstarted.
