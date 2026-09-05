# Task 1 verification record

Date: 2026-09-05. Checkout: `D:\Shoulder`, branch `task-1-foundation`.
Scope: Task 1 completion under ADR 0012. The owner later authorized the Task 1
commit, branch push, and pull request. No cloud mutation, deployment,
authentication, database, worker process, or player data.

## Files

Created: root Node/pnpm and Python/uv manifests and lockfiles; .node-version,
.python-version, .npmrc, .gitignore, .gitattributes, .dockerignore, biome.json;
apps/web package/config, app layout/page/styles/health, inline brand components,
environment example and public OFL license; services/api main and package marker,
environment example; services/worker README; packages/contracts generated OpenAPI
and TypeScript plus README; scripts/bootstrap.ps1, check.ps1, export_openapi.py;
tests/test_health.py, repository.test.mjs, smoke.spec.mjs; playwright.config.mjs;
.github/workflows/ci.yml; infra/api.Dockerfile, fly.toml, README; ADR 0012; this record.

Updated: README.md, STATUS.md, assets/README.md, docs 00/02/06/08/09/11/13,
and ADR 0010. Existing SVG files are used unchanged. No db/ or cv/ implementation.

## Exact direct dependencies

| Role | Package | Version |
|---|---|---|
| Web runtime | next | 16.3.4 |
| Web runtime | react, react-dom | 19.2.8 each |
| Font assets | @fontsource-variable/inter-tight | 5.3.0 |
| Web build | tailwindcss, @tailwindcss/postcss | 4.3.3 each |
| Types | @types/react | 19.2.18 |
| Types | @types/react-dom | 19.2.7 |
| Types | @types/node | 24.13.3 |
| Compiler | typescript | 5.9.3 |
| Format/lint | @biomejs/biome | 2.5.12 |
| Browser tests | @playwright/test | 1.63.0 |
| Accessibility | @axe-core/playwright | 4.13.0 |
| Contract generation | openapi-typescript | 7.13.0 |
| API runtime | fastapi | 0.141.1 |
| API schema | pydantic | 2.13.5 |
| ASGI server | uvicorn | 0.52.4 |
| API tests | httpx | 0.28.1 |
| Python format/lint | ruff | 0.16.6 |
| Python types | mypy | 2.3.1 |
| Dependency audit | pip-audit | 2.10.1 |

All direct pins are exact; transitive resolutions and integrity hashes are in
pnpm-lock.yaml and uv.lock. No production dependency beyond the specified web/API
stack and font binaries was introduced. Rationale is in ADR 0012.

Toolchain: existing Windows Node 24.11.1 / npm 11.6.2; explicit pnpm 11.25.0;
official checksum-verified uv 0.12.10 in .tools; Astral-managed CPython 3.11.16 in
.tools/python. No system-wide tool installation. The manifest permits Node 24
patches for Vercel; .node-version and bootstrap/CI pin the locally tested version.
CI actions are pinned to immutable revisions verified against official repositories.

## Commands and checks

All commands run from D:\Shoulder. In this table, `pnpm` means the exact command
prefix `npm.cmd exec --yes --package=pnpm@11.25.0 -- pnpm`. Some repair commands
used npm's `--offline` flag after the exact package was cached. `uv` means
`.\.tools\uv.exe`. CI invokes those same pinned tools directly.

| Command/check | Outcome |
|---|---|
| `Get-Content` of goal and required repository/asset documents; `rg --files`, font/prerequisite/reference searches | Read scope and reconciled affected references |
| `Get-Command node,npm,python,py,uv,git,gh`; `node --version`; `npm.cmd --version` | Node 24.11.1 and npm 11.6.2 available; Python/uv initially absent |
| `git status --short`, `git branch --show-current`, `git remote -v`, `git ls-files assets/brand` | Inspected existing changes, main, configured origin, and both tracked SVGs |
| `git switch -c task-1-foundation` | Passed with authorized filesystem access; existing edits preserved |
| `npm.cmd view <package> version` for all JS direct packages, pnpm; TypeScript 5.9.3, Node types 24, pnpm engines and Next peers | Exact versions/compatibility verified against npm |
| `Invoke-RestMethod https://pypi.org/pypi/<package>/json` for uv and Python dependencies | Exact available versions verified |
| Official GitHub uv release and action commit metadata via `Invoke-RestMethod` | uv archive/checksum and immutable action revisions resolved |
| PowerShell XML parsing of both supplied SVGs | Valid SVG roots/namespaces; paths and currentColor inspected |
| `Invoke-WebRequest` official uv 0.12.10 Windows archive; `Get-FileHash -Algorithm SHA256`; `Expand-Archive`; `uv --version` | Download matched f65744f94072152b1f86ba2aace4d01f1124d9a8ecb235805039e3718c36cac2 |
| `uv python list 3.11 --only-downloads`; `uv python install 3.11.16 --no-bin`; `uv sync` | Python installed locally; lock resolved and 48 dependency packages installed |
| `pnpm install` | Exact direct dependencies installed; pnpm-lock.yaml generated |
| `Copy-Item apps/web/node_modules/@fontsource-variable/inter-tight/LICENSE apps/web/public/licenses/inter-tight-OFL.txt` | Included font license preserved verbatim |
| `pnpm exec playwright install chromium firefox webkit` | Pinned browser builds installed |
| `.\scripts\bootstrap.ps1` | Exact README setup passed: version/checksum checks, `uv sync --locked`, `pnpm install --frozen-lockfile`, browser installation |
| `pnpm dev:web` | README command served / and /health locally |
| `uv run --locked python -m uvicorn services.api.main:app --host 127.0.0.1 --port 8000` | README command served API locally |
| `Invoke-RestMethod http://127.0.0.1:3000/health` and port 8000 equivalent | Both returned status ok |
| `(Invoke-WebRequest http://127.0.0.1:3000).StatusCode` | 200; servers then stopped with Ctrl+C |
| `pnpm exec biome check --write .`; `pnpm exec biome migrate --write` | Formatted implementation; migrated config and explicitly enabled recommended preset |
| `uv run --locked ruff format .`; `uv run --locked ruff check . --fix` | Python formatted/linted |
| `uv run --locked mypy --explicit-package-bases` | Confirmed namespace-package repair |
| `pnpm format:check` | Passed |
| `pnpm lint` | Passed with recommended rules enabled |
| `pnpm typecheck` | Passed: Next route generation and tsc --noEmit |
| `pnpm test` | Two Node tests passed: secret-file exclusions/source scan and font pin/license parity |
| `uv run --locked ruff format --check .` | Passed |
| `uv run --locked ruff check .` | Passed |
| `uv run --locked mypy` | Passed, strict checking |
| `uv run --locked python -m unittest discover -s tests -p test_*.py` | API test passed: exact health payload, no product route |
| `uv run --locked python -m scripts.export_openapi`; `pnpm contracts` | Generated from FastAPI; before/after hashes verify no drift |
| `pnpm build` | Optimized production build passed; /, /health, and framework 404 only |
| `pnpm smoke` | Three browser projects passed, 27 responsive screenshots total |
| `pnpm audit --audit-level=low` | No known vulnerabilities |
| `uv run --locked pip-audit` | No known vulnerabilities |
| `pnpm licenses list --json` | Installed license inventory inspected; Fontsource OFL-1.1 preserved |
| Inline Node/js-yaml configuration audit and Python tomllib/importlib.metadata audit | CI trigger/permissions/shared check, exact manifest-lock pins, Vercel/Fly configuration, health-only OpenAPI, and license metadata for all 48 Python packages passed |
| PowerShell Parser.ParseFile on bootstrap/check scripts | No parse errors |
| `git diff --check`, final `git status --short` and diff review | Whitespace and final scope/privacy review; no commit or push |

`scripts/check.ps1` is the shared executable sequence for format/lint/types,
repository and API tests, generated-contract drift, build, smoke, and diff checks.
The CI workflow invokes that script after frozen installs, then vulnerability
checks. The hosted PR run begins after the separately authorized finalization.

## Diagnosed failures and repairs

- Restricted sandbox npm metadata/cache access and Git branch creation returned
  EACCES/permission denied. The same authorized operations passed with tool-level
  access approval; no machine-wide security setting changed.
- Initial uv default cache access failed; project configuration now uses .cache/uv.
- Initial uv resolution reported normalization of a transitive package's invalid
  historical version metadata; the resulting lock installs without that warning.
- Biome's old recommended field was deprecated. Migration alone produced preset
  none; it was corrected explicitly to recommended and lint rerun.
- mypy initially assigned two names to the API module. explicit_package_bases
  resolved namespace discovery; strict type checking passes.
- Starlette deprecated its httpx TestClient wrapper. The test now uses httpx's
  ASGITransport directly; no additional dependency or warning suppression.
- Playwright initially could not launch a Windows path containing forward slashes.
  The executable is now resolved and quoted. Inherited NO_COLOR is removed inside
  the Playwright process because Playwright supplies FORCE_COLOR.
- Next dev generated unwanted local AGENTS/CLAUDE files. The documented native
  agentRules setting disables that behavior; generated files were removed.
- Contract export explicitly writes UTF-8/LF so Windows and Linux produce the same
  bytes; .gitattributes keeps the distributed OFL text LF as well. Node engines allow Vercel's managed 24.x patch while local/CI remain pinned.
- The one-off configuration audit initially referenced yaml instead of the installed js-yaml dependency and lost regex escaping in tool orchestration; both diagnostic-command issues were corrected and the audit passed.
- A documentation edit command had a PowerShell here-string typo and one patch
  mismatched formatter output. Both were corrected and reapplied before review.

## Browser and manual evidence

Chromium, Firefox, and WebKit pass at 320x568, 360x800, 390x844, 430x932,
768x1024, 1024x768, 1280x800, 1440x900, and 1920x1080. Each verifies no horizontal
overflow. The test also checks accessible names, original SVG paths/viewBoxes,
no img logos, all page requests on the local origin, WOFF2 requests, font weights
400/500/600, exact served license, no page errors, and axe accessibility violations.

Screenshots are in ignored test-results/. The 320px and 1440px Chromium images
were visually inspected: the provided artwork, paper/ink palette, text hierarchy,
and spacing render without clipping. This is a static shell with no interactive
controls or product states; form focus, auth, video, and player workflow testing
belong to later tasks. Desktop browser engines do not prove real iOS/Android
device behavior; public phone deployment checks remain pending approval.

License inventory includes ordinary permissive licenses, Fontsource OFL-1.1,
axe's MPL-2.0, caniuse data CC-BY-4.0, and the transitive sharp native package's
Apache-2.0/LGPL-3.0-or-later notices. No bundled dependency is modified; package
license notices are retained. Deployment packaging must preserve its native
dependency notices as well as the explicitly served font license.

## Remaining approval/external work

The owner authorized the Task 1 commit, branch push, and pull request after this
local verification. Cloud deployment, resource creation, GitHub setting changes,
and PR merge remain unauthorized. Deployment targets, region, account access,
and repository visibility remain unconfirmed. infra/ contains prepared settings,
not evidence of a successful Docker/Vercel/Fly deployment. No Docker daemon was
installed just to validate a deployment that is awaiting approval.

Task 1 local acceptance is governed by ADR 0012. Task 2 is next and not started.
The recommended next local command is `.\scripts\check.ps1`.
