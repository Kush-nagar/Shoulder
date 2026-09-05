# Shoulder status

Update this file at every task boundary. Keep it factual and short.

## Current state

- Planning package: reconciled; documentation-only reconciliation complete
- Application code: not started
- Current phase: Phase A — Foundation
- First implementation task: Task 1 — Repository, CI, and first deployment; gated by the pre-start inputs below
- Repository: GitHub configured at `Kush-nagar/Shoulder`; initial handoff committed and pushed
- Git evidence: `main` and recorded `origin/main` agree (`git rev-list --left-right --count HEAD...origin/main` returned `0 0`); initial handoff commit includes `5eb7a7f`
- Canonical root: `D:\Shoulder`; environment unchanged
- Last verified date: 2026-09-04

## Completed tasks

- Documentation reconciliation (non-numbered): complete after cross-reference, task-dependency, and contradiction checks; ADRs 0006–0011 added. The owner subsequently authorized committing and pushing the reviewed documentation changes.
- Numbered implementation tasks: none complete.

## Current task

- Task: documentation reconciliation — complete
- Scope: handoff Markdown and ADRs only; no application code, dependencies, cloud setup, migrations, CI, or environment files created
- Checkout: `D:\Shoulder`, `main`; one writer; documentation-only commit/push authorized after final review
- Next: Task 1, not started; do not treat the owner-provided asset gate as satisfied

## Coding blockers and setup readiness

- Contract blockers from the audit: resolved. Task 3 handles identity only; Task 4 owns role-aware `/v1/me` plus baseline RLS/tests; Task 5 extends protection.
- Execution toolchain is not verified ready: the audit found a failing ordinary npm launcher, no verified Python 3.11, and required infrastructure tools unavailable on PATH. Pin/repair/verify tooling only in a separately authorized setup or implementation session; nothing was installed during this reconciliation.
- Keep Windows-native work in the canonical root unless the owner authorizes an environment change. WSL was not installed at audit time.

## Remaining owner-provided prerequisites

| Required input or confirmation | Needed by | State |
|---|---|---|
| Repository private/public visibility | Before Task 1 starts | GitHub host configured; visibility not yet confirmed |
| Original vector source/usage approval and every approved SVG variant in `docs/08-brand.md` | Before Task 1 starts | Missing; PNG reference only, receipt tracked in `assets/README.md` |
| Local Inter Tight files for weights 400/500/600, license, version, provenance | Before Task 1 starts | Missing; no substitutes assumed |
| Deployment access and intended Vercel/Fly.io targets | Task 1 deployment completion | Not verified; no account or credential request made here |
| Production domains | Before Task 3 auth callback/cookie setup | Owner choice outstanding |
| Coach/organization footage permission and participant notice | Before real footage or minors' data anywhere | Owner confirmation required |
| Season end timestamp, collateral shared-footage erasure policy, responsible deletion/incident operator, and actual provider backup expiry of at most 30 days | Before real-data onboarding/Task 22 release gate | Owner operational confirmation required under ADR 0009; not a legal guarantee |

Task 1 is the first task in sequence and its contract is safe to implement once the pre-start inputs and tooling readiness are satisfied. It is **not cleared to start now** while required vectors/fonts and visibility confirmation are missing. These are explicit prerequisites, not unresolved implementation design choices.

## Decisions awaiting real evidence

- Whether a single 720p coach playback MP4 meets seek and startup targets.
- Whether SoccerMaster Step 3 can run without the SAM2 Step 2 artifact.
- Whether computer vision saves review time after the manual workflow is used for three games.

## Decision log

- MVP uses coach-only progressive MP4, not HLS.
- Player evidence is exported to separate clip objects before publication.
- Next.js owns Supabase session cookies; FastAPI validates forwarded bearer JWTs.
- `user_account.id` is the Supabase Auth user UUID.
- Product tables live in a non-exposed `app` schema; helpers live in `private`.
- Three-to-six-clip publishing uses explicit publication and item rows with atomic final visibility.
- Judgment edits append immutable versioned snapshots; replacement publication preserves the old player-visible snapshot until the complete new set succeeds.
- Reflection text is mutable/deletable only by its player author, with no retained text history and bounded backup/restore handling.
- Source expiry starts at upload completion; failed work has earlier deadlines; season expiry uses an explicit timestamp. Shared-footage erasure removes all affected team videos and dependent evidence, including other players' affected clips, under an owner-confirmed operating policy.
- Review has no global navigation rail and provides three visible accessible verdict choices. Approved vectors and fonts are pre-Task-1 inputs.
- Phase D CV cleanup retains judgment-referenced observations with machine provenance cleared; mandatory judgment FKs remain intact.
- `AGENTS.md` is canonical; `CLAUDE.md` imports it.

## Documentation reconciliation verification

- Changed: canonical product, architecture, schema, API, UI/design, security, testing, task sequence, asset requirements, README, this status, and ADRs; see the reconciliation commit for the exact file set.
- Checks: in-memory Node audit of all 31 Markdown files, internal Markdown/backtick references (including `@AGENTS.md` imports), 31 numbered tasks and prerequisite ordering, and stale contradictory phrases; manual cross-document review of all eight audit findings.
- Result: references resolve; no invalid/circular numbered prerequisites; superseded reflection, RLS/auth sequence, publication, retention, review-rail/verdict, asset, and CV deletion wording reconciled. `git diff --check` passed; Git scope check confirmed exactly 24 changed/added Markdown files and no non-document changes. Windows line endings were normalized in the changed documents to remove mixed-ending warnings.
- Application tests/lint/types: not applicable; no application implementation or packages exist yet. No tests were skipped to declare a numbered task complete.
- ADRs: `docs/decisions/0006-foundation-auth-and-rls-sequence.md`, `docs/decisions/0007-author-controlled-reflections.md`, `docs/decisions/0008-judgment-revisions-and-republication.md`, `docs/decisions/0009-retention-and-shared-footage-deletion.md`, `docs/decisions/0010-review-workspace-and-asset-prerequisites.md`, `docs/decisions/0011-cv-provenance-deletion.md`.

## Handoff template

When completing a task, replace the current-task block and append:

- Changed:
- Tests run:
- Result:
- Known limitations:
- ADRs added:
- Next eligible task:
