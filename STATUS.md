# Shoulder status

Update this file at every task boundary. Keep it factual and short.

## Current state

- Planning package: complete
- Application code: not started
- Current phase: Phase A — Foundation
- Next eligible task: Task 1
- Last verified date: 2026-08-24

## Completed tasks

- None

## Current task

- Task: 1 — Repository, CI, and first deployment
- Owner: unassigned
- Branch: unassigned
- Started: not started
- Expected output: repository skeleton, CI, and phone-accessible web/API health checks

## Active blockers

- Confirm the final repository host and private/public visibility before Task 1.
- Obtain coach/organization permission before uploading real team footage anywhere.
- Choose production domains before auth callback and cookie configuration in Task 3.

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
- `AGENTS.md` is canonical; `CLAUDE.md` imports it.

## Handoff template

When completing a task, replace the current-task block and append:

- Changed:
- Tests run:
- Result:
- Known limitations:
- ADRs added:
- Next eligible task:
