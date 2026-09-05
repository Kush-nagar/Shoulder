# 06 — Build order

This is the daily execution file. Implement one numbered task per branch. A prerequisite is complete only when its named test and definition of done are satisfied and `STATUS.md` records the result.

Tasks 1–22 contain zero machine learning.

## Phase A — Foundation

### Task 1 — Repository, CI, and first deployment

**Prerequisites:** none  
**Read:** `AGENTS.md`, `docs/02-architecture.md`, `docs/11-testing-quality.md`

Create the monorepo boundaries, package tooling, environment examples, lint/type/test jobs, and minimal web/API health routes. Deploy the web shell to Vercel and API health endpoint to Fly.io.

**Test:** a trivial pull request runs every CI job.  
**Done:** both production health routes load on a phone; no secrets or sample player data exist.

### Task 2 — Local infrastructure

**Prerequisites:** 1  
**Read:** `docs/02-architecture.md`

Provide Supabase CLI-managed local Auth/Postgres plus MinIO in Docker Compose, repeatable setup commands, `.env.example`, and pinned tool/image versions. Use the project-supported Postgres 16 image and do not run a second application Postgres. Verify the current Supabase CLI command surface rather than guessing it; record an ADR if the local image cannot match the Postgres target.

**Test:** clean checkout to healthy services using the documented command.  
**Done:** a contributor can start, stop, migrate, and reset local services without tribal knowledge.

### Task 3 — Supabase Auth and same-origin session boundary

**Prerequisites:** 1  
**Read:** `docs/02-architecture.md`, `docs/04-api.md`, `docs/10-security-privacy.md`

Implement magic link request/callback/sign-out in Next.js, the current proxy/session-refresh convention, secure cookies, the same-origin BFF, JWT verification in FastAPI, and `/v1/me`. Use the current Supabase SSR `getClaims()` path to verify identity; if `getSession()` is used to retrieve the token for FastAPI, do not authorize from its user object. Pin Supabase packages and commit the lockfile.

**Test:** valid, refreshed-expired, malformed, wrong-issuer, wrong-audience, reused callback, and signed-out sessions.  
**Done:** coach and player sessions work on the production domains; the browser contains no secret key; FastAPI rejects an unverified token.

### Task 4 — Core identity, team, and player schema

**Prerequisites:** 2, 3  
**Read:** `docs/03-schema.md`

Create the non-exposed `app` schema, private helper boundary, and Alembic migrations for `user_account`, `team`, `team_membership`, and `player`. Bind application IDs to `auth.users.id`. Create the production API database role with no RLS bypass and no unintended Data API exposure.

**Test:** migrate up/down; profile synchronization; duplicate active jersey and duplicate linked player checks.  
**Done:** schema exists locally and in the linked development project, with no second identity UUID.

### Task 5 — Complete RLS policy matrix and isolation harness

**Prerequisites:** 4  
**Read:** `docs/03-schema.md`, `docs/10-security-privacy.md`

Create policy helpers and policies for the current tables. Build a reusable integration harness that executes through the production-equivalent database role and transaction-local user context.

**Test:** two coaches, two players on one team, and a second team; every forbidden read/write is empty, 404, or denied. Commenting out a policy makes CI fail.  
**Done:** tables are not owned by a bypass role; RLS is enabled/forced as designed; the isolation suite is mandatory in CI.

### Task 6 — Roster workflows

**Prerequisites:** 5  
**Read:** `docs/04-api.md`, `docs/05-ui.md`, `docs/09-frontend-design-system.md`

Build team/roster API, bulk preview and commit, single-player edits, archive, and invitation/link transaction.

**Test:** API 401/403/404/409/422 cases; bulk all-or-nothing; keyboard and screen-reader form flow.  
**Done:** a coach can add 20 players in under five minutes without collecting player emails.

### Task 7 — Development goals

**Prerequisites:** 6  
**Read:** `docs/01-product.md`, `docs/03-schema.md`, `docs/05-ui.md`

Build goal schema/API/UI with one active goal per player and explicit status transitions.

**Test:** player reads only own goal; second active goal is rejected; coach outside team is denied.  
**Done:** a real roster player has an active goal in the coach interface.

## Phase B — Video

### Task 8 — R2 multipart service

**Prerequisites:** 1, 5  
**Read:** `docs/02-architecture.md`, `docs/04-api.md`, `docs/10-security-privacy.md`

Create the `game`, `video`, and `video_upload_part` schema with RLS, then build private-bucket configuration, strict CORS, multipart start/sign/list/complete/abort, object-specific signed GET, and upload-part persistence. Use MinIO for integration tests.

**Test:** 2 GB generated file, interrupted part, repeated complete request, wrong object/verb/part, and expired URL.  
**Done:** failed parts retry without repeating completed parts; video bytes never pass through FastAPI.

### Task 9 — Honest resumable upload UI

**Prerequisites:** 6, 8  
**Read:** `docs/05-ui.md`, `docs/09-frontend-design-system.md`

Build game metadata, file validation, three-part concurrency, local resume metadata, server reconciliation, reselect-same-file recovery, and accurate copy about tab closure.

**Test:** Playwright interrupts network, reloads, reselects the file, resumes missing parts, and completes.  
**Done:** the UI never claims upload continues after tab close and never restarts completed parts.

### Task 10 — Durable Postgres worker queue

**Prerequisites:** 8  
**Read:** `docs/02-architecture.md`, `docs/03-schema.md`

Add job schema, idempotency keys, claims, leases, heartbeat, backoff, cancellation, terminal failure, and stuck-job recovery.

**Test:** two workers claim 100 jobs with no double execution; crashed lease is safely recovered; idempotent enqueue creates one job.  
**Done:** concurrency test is stable across repeated runs.

### Task 11 — Coach playback transcode

**Prerequisites:** 8, 10  
**Read:** `docs/00-decisions.md`, `docs/02-architecture.md`

Probe the original safely and create a 720p, fast-start H.264/AAC MP4 with bounded resources and frequent keyframes. Store metadata and sanitized progress.

**Test:** golden 30-second fixture; malformed file; ffmpeg failure; byte-range playback and seek.  
**Done:** a full-length fixture starts and seeks within the performance budgets. If not, record measurements and propose an ADR before HLS.

### Task 12 — Thumbnail sprites

**Prerequisites:** 11  
**Read:** `docs/02-architecture.md`

Create timeline sprites and a timestamp index with bounded dimensions and deterministic layout.

**Test:** golden fixture produces stable index geometry; timestamp-to-sprite lookup unit tests.  
**Done:** the full timeline appears quickly without loading hundreds of image objects.

### Task 13 — Coach video player and timeline

**Prerequisites:** 11, 12  
**Read:** `docs/05-ui.md`, `docs/09-frontend-design-system.md`

Build the native video player wrapper, signed-URL refresh preserving time, transport controls, scrubber, and marker layer.

**Test:** timeline math, expired URL refresh, keyboard transport, accessible control names, and no layout shift.  
**Done:** scrubbing and keyboard transport meet the named budgets on a laptop.

## Phase C — The manual product

### Task 14 — Manual clip marking

**Prerequisites:** 7, 13  
**Read:** `docs/03-schema.md`, `docs/05-ui.md`

Add observation schema/API and the full I/O marking flow. Enforce video/player/team consistency and time bounds.

**Test:** keyboard unit tests and Playwright marking flow; shortcut suppression in text fields.  
**Done:** a coach marks a valid clip in under six seconds without a mouse.

### Task 15 — Coach judgments

**Prerequisites:** 14  
**Read:** `docs/03-schema.md`, `docs/04-api.md`

Add judgment schema/API, verdicts, comments, clip adjustments, and server-derived author. Preserve rejected judgments.

**Test:** spoofed author field rejected; cross-team goal rejected; not-relevant never publishable.  
**Done:** applied, opportunity, and rejected drafts persist correctly.

### Task 16 — Draft preservation and conflict recovery

**Prerequisites:** 15  
**Read:** `docs/05-ui.md`, `docs/11-testing-quality.md`

Persist local drafts on every change, reconcile optimistic API writes, restore after reload/offline, and handle stale versions without loss.

**Test:** mark five clips, edit comments, force reload and network failure, then recover all five exactly.  
**Done:** draft-preservation test is load-bearing in CI.

### Task 17 — Player-only clip export and batch publish

**Prerequisites:** 10, 15, 16  
**Read:** `docs/00-decisions.md`, `docs/02-architecture.md`, `docs/04-api.md`

Add `review_publication`, ordered publication items, evidence clip schema, exact-boundary export, publication state machine, batch validation, atomic current-object swap, retry, and withdrawal.

**Test:** 3–6 rule, request/job idempotency, ordered-set persistence, concurrent overlapping publish rejection/serialization, exact duration tolerance, partial batch failure/retry, atomic visibility, and full-match URL denial.  
**Done:** the requested publication survives worker restart and player visibility begins only after every current clip object is ready; a player token cannot sign coach playback.

### Task 18 — Player mobile experience

**Prerequisites:** 17  
**Read:** `docs/05-ui.md`, `docs/09-frontend-design-system.md`, `docs/10-security-privacy.md`

Build player home, goal/evidence sequence, object-specific clip signing, low-data preload behavior, and safe verdict copy.

**Test:** 320/375/430px visual cases; keyboard/screen reader basics; Player B cannot read or sign Player A's evidence.  
**Done:** a linked player opens only their clips on a phone; no full video identifier or URL appears in the response or DOM.

### Task 19 — Optional reflections

**Prerequisites:** 18  
**Read:** `docs/03-schema.md`, `docs/05-ui.md`

Build one optional, editable/removable reflection per judgment and the coach reflection feed. Preserve unsent player text through a transient failure.

**Test:** ownership, length, duplicate, skip flow, and retry.  
**Done:** reflection saves and appears to the correct coach without gating another clip.

### Task 20 — Email delivery

**Prerequisites:** 3, 17, 19  
**Read:** `docs/05-ui.md`, `docs/10-security-privacy.md`

Add Resend templates, verified redirect allowlist, one evidence-set email after clips are ready, and coach failure messages.

**Test:** mocked send, duplicate-event suppression, link target validation, and no private content in subject lines.  
**Done:** the email opens the correct authenticated goal page and cannot redirect off-site.

### Task 21 — Development timeline

**Prerequisites:** 18, 19  
**Read:** `docs/01-product.md`, `docs/05-ui.md`, `docs/09-frontend-design-system.md`

Build filled/outlined evidence dots grouped by game for coach and player views.

**Test:** accessibility text equivalent; no score/percentage/aggregate fields in API or UI.  
**Done:** five games form a readable evidence record without implying a performance metric.

### Task 22 — Retention, deletion, and first-party product events

**Prerequisites:** 17–21  
**Read:** `docs/03-schema.md`, `docs/10-security-privacy.md`, `docs/11-testing-quality.md`

Implement raw-video lifecycle verification, hard-delete job, account/player archive rules, safe operational events, and SQL queries for review duration/open rate.

**Test:** seeded database and bucket hard delete; no player names/comments/URLs in events; retention job is idempotent.  
**Done:** deletion removes every mapped object and row, and product operations can be measured without third-party analytics.

## Mandatory real-use gate

Do not start Task 23 until all are true:

- The coach completes two consecutive reviews without developer intervention.
- Three real games have passed through the complete loop.
- Median full-roster review is under 25 minutes.
- At least half of invited players open within 48 hours without a reminder.
- At least one player submits an optional reflection.
- The coach chooses to use Shoulder for the next game.
- No unresolved cross-player, full-match, upload-loss, or deletion defect exists.

If the gate fails, fix Phase C. Computer vision cannot repair a weak loop.

## Phase D — Offline CV feasibility

### Task 23 — Segment preparation

**Prerequisites:** gate passed  
**Read:** `docs/07-cv.md`, `docs/13-licenses-and-sources.md`

Create a private segment-to-frame-bundle tool matching the current SoccerMaster GSR input format and an immutable manifest/checksum.

**Test:** bundle validates against a small known fixture; timestamps map exactly back to original milliseconds.  
**Done:** one selected segment can be prepared and verified without a GPU.

### Task 24 — Private RunPod environment

**Prerequisites:** 23  
**Read:** `docs/07-cv.md`, `docs/13-licenses-and-sources.md`

Recheck every relevant license and current upstream install instruction. Build the separate private pod, encrypted storage path, network volume, pinned environment, and copy-ready runbook. Do not commit upstream code or weights.

**Test:** imports, one upstream sample, destruction/recreation from template, and checksum preservation.  
**Done:** the runbook succeeds twice and the pod can be destroyed without losing permitted weights or artifacts.

### Task 25 — First real run and cost record

**Prerequisites:** 24  

Run one five-to-ten-minute segment through Step 1 and the accelerated Step 3. Test whether Step 2 can be skipped; record both the result and cost.

**Test:** manual artifact inspection; wall time, GPU type, storage, and cost recorded.  
**Done:** artifact JSON contains plausible tracklets, and a short ADR records the Step 2 decision.

### Task 26 — Detection/tracking evaluation

**Prerequisites:** 25  

Annotate a bounded sample across three games and calculate detection recall, tracklet purity, and duration. Do not tune against the final held-out game.

**Test:** reproducible evaluation from frozen labels and artifacts.  
**Done:** measured results are written down. Proceed only if the footage supports useful retrieval; otherwise improve camera setup or stop.

### Task 27 — Artifact ingest

**Prerequisites:** 25  
**Read:** `docs/03-schema.md`, `docs/07-cv.md`

Store immutable run metadata, a tracklet index in Postgres, and per-frame trajectories in Parquet. Apply the original segment offset exactly once.

**Test:** frozen artifact produces byte-stable semantic rows and Parquet schema.  
**Done:** tracklets are inspectable without restarting a GPU.

## Phase E — Evidence retrieval

### Task 28 — Coach tracklet assignment

**Prerequisites:** 27  

Build thumbnail-based tracklet assignment. Jersey numbers and team side are hints, never identity decisions.

**Test:** no assignment from model output without a coach action; corrections persist.  
**Done:** a coach assigns a realistic segment in under two minutes.

### Task 29 — Deterministic signals and receiving candidates

**Prerequisites:** 28  

Derive bounded, explainable image-space signals and rule-based possession/receiving events. Use an asymmetric context window before/after receive.

**Test:** hand-checked fixture; temporal IoU and Recall@30 against labeled events.  
**Done:** candidates beat chronological/random baselines and include a plain feature record.

### Task 30 — CV candidates in the existing review screen

**Prerequisites:** 29, 15  

Write `cv_candidate` observations, deduplicate overlaps, cap volume, and show them only to coaches in the Task 14 screen.

**Test:** golden artifact deterministic observations; candidates cannot publish without a human judgment.  
**Done:** compare manual and CV-assisted review time plus kept clips per segment.

## Phase F — Only if data justifies it

### Task 31 — Candidate ranking model

**Prerequisites:** Task 30 and at least 2,000 human judgments

Train only on candidate features and human keep/reject labels. Rank review order; never produce player-facing text or ability scores.

**Test:** held-out Precision@10 and review-time comparison against chronological ordering.  
**Done:** ranking materially saves review time without reducing retrieval recall. Otherwise keep the rules.
