# ADR 0012 — Task 1 local acceptance and tooling

- Status: Accepted by the owner's Task 1 goal
- Date: 2026-09-05

## Decision

Task 1 is complete when its local implementation and configured checks pass.
Deployment, cloud resources, GitHub settings, commits, pushes, and a hosted PR run
remain pending explicit follow-up approval. This narrows the original production
deployment acceptance in Task 1 without claiming that deployment occurred.

The owner named `assets/brand/shoulder-mark.svg` and
`assets/brand/shoulder-wordmark.svg` as the approved Task 1 inputs. These two
currentColor SVGs satisfy the health shell's asset gate. Other placement-specific
variants remain required before those placements ship, not before this shell.
Repository visibility remains unverified and unchanged; the owner authorized
local implementation without changing it.

Use the existing Windows-native Node 24.11.1 installation, pnpm 11.25.0 via an
explicit npm package spec, project-local uv 0.12.10, and project-local CPython
3.11.16. `scripts/bootstrap.ps1` verifies uv's official archive checksum and
installs from lockfiles. No system-wide installation is required. CI uses the
same versions. TypeScript remains on compatible stable 5.9.3 rather than changing
compiler generation during foundation setup.

The web app uses the approved Next.js/React stack, Tailwind's build integration,
and Fontsource Inter Tight 5.3.0 for WOFF2 binaries. Native fonts cannot provide
the approved family. FastAPI/Pydantic provide the specified API contract;
Uvicorn serves ASGI. Development dependencies are limited to Biome, TypeScript
types, Ruff, mypy, httpx, Playwright/axe, openapi-typescript, and pip-audit for the
requested format, lint, type, API/browser, accessibility, contract, and dependency
checks. Tests use Node's test runner and Python unittest. No database or worker
runtime dependency is introduced.

## Validation

`scripts/check.ps1` runs local and CI quality gates, including generated-contract
drift and the production web build. The browser suite launches the two real
servers, checks health, approved vector paths, same-origin fonts, license delivery,
accessibility, and responsive overflow. Frozen installs and dependency audits
are separate bootstrap/CI steps. See `docs/task-1-verification.md` for evidence
and the deployment limitations in `infra/README.md`.
