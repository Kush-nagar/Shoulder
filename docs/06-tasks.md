# 06 — Build order

This is the daily execution file. Implement one numbered task per branch. A prerequisite is complete only when its named test and definition of done are satisfied and `STATUS.md` records the result.

Tasks 1–22 contain zero machine learning.

Every task introducing a protected table includes its Alembic migration, baseline RLS, grants, and runtime-role isolation tests in that same task. No later harness task is permission to defer protection. Non-numbered prerequisites and owner inputs are tracked in `STATUS.md`; the documentation reconciliation is separate from Task 1.

## Phase A — Foundation

### Task 1 — Repository, CI, and first deployment

**Prerequisites:** no numbered tasks; completed documentation reconciliation; the owner-approved Task 1 mark and wordmark in `assets/README.md`; working pinned Windows-native tooling. The owner authorized local implementation with repository visibility unchanged and unverified; see `docs/decisions/0012-task-1-local-acceptance.md`.

**Read:** `AGENTS.md`, `docs/02-architecture.md`, `docs/08-brand.md`, `docs/09-frontend-design-system.md`, `docs/11-testing-quality.md`, `docs/13-licenses-and-sources.md`, `docs/decisions/0010-review-workspace-and-asset-prerequisites.md`, `docs/decisions/0012-task-1-local-acceptance.md`, `assets/README.md`, `STATUS.md`

Use the existing GitHub repository and committed initial handoff; do not reinitialize Git. Create the monorepo boundaries, package tooling, environment examples, lint/type/test jobs, and minimal web/API health routes. Prepare Vercel web and Fly.io API deployment configuration. Under the owner-approved Task 1 scope, deployment, cloud resources, repository settings, commits, pushes, and hosted PR execution remain pending explicit follow-up approval; local completion does not claim production deployment. Asset placeholders or a traced wordmark do not satisfy the vector pre-start gate. Inter Tight may be added during Task 1 through `@fontsource-variable/inter-tight`. Self-host its WOFF2 assets covering weights 400/500/600 through `next/font/local`, preserve its included SIL Open Font License with the assets and in distributions, and make no runtime request to Google Fonts. Pin an exact package version in the dependency manifest and project lockfile. After installation, document the exact resolved version, package provenance, asset paths, and retained license location in `assets/README.md`; record the resolved version and completion in `STATUS.md`. Font receipt is not a pre-start prerequisite; the approved family and visual specification are unchanged.

**Test:** the pull-request workflow is configured to run the same passing local quality checks; an actual hosted PR run awaits push approval; verify the exact package version against the project lockfile and asset record, retained SIL Open Font License, weights 400/500/600, and same-origin WOFF2 loading with no runtime Google Fonts requests.

**Done:** both local health routes return the documented healthy response, the shell passes responsive browser smoke checks, and deployment configuration is prepared with public phone verification pending explicit approval; no secrets or sample player data exist; Inter Tight WOFF2 assets are self-hosted, the included SIL Open Font License is preserved, runtime Google Fonts requests are absent, and the exact lockfile-resolved package version is documented after installation.

### Task 2 — Local infrastructure

**Prerequisites:** 1

**Read:** `docs/02-architecture.md`

Provide Supabase CLI-managed local Auth/Postgres plus MinIO in Docker Compose, repeatable setup commands, `.env.example`, and pinned tool/image versions. Use the project-supported Postgres 16 image and do not run a second application Postgres. Verify the current Supabase CLI command surface rather than guessing it; record an ADR if the local image cannot match the Postgres target.

**Test:** clean checkout to healthy services using the documented command.

**Done:** a contributor can start, stop, migrate, and reset local services without tribal knowledge.

### Task 3 — Verified authentication and session identity

**Prerequisites:** 1, 2

**Read:** `docs/02-architecture.md`, `docs/04-api.md`, `docs/10-security-privacy.md`

Implement magic link request/callback/sign-out in Next.js, the current proxy/session-refresh convention, secure cookies, the same-origin BFF token forwarding boundary, and independent JWT verification in FastAPI. Prove verified identity through integration tests and a neutral signed-in state. Do not implement role-aware `/v1/me`, coach/player routing, memberships, or product authorization here; those are Task 4 acceptance. Use the current Supabase SSR `getClaims()` path to verify identity; if `getSession()` retrieves the token, do not authorize from its user object. Pin Supabase packages and commit the lockfile.

**Test:** valid, refreshed-expired, malformed, wrong-issuer, wrong-audience, wrong-algorithm, reused callback, CSRF/origin, safe redirect, cookie propagation, and signed-out sessions; no role privilege is inferred from identity.

**Done:** verified sign-in/sign-out works on owner-confirmed production domains; the browser contains no secret key; FastAPI rejects unverified tokens; no role-aware stub is counted as completed functionality.

### Task 4 — Core schema, baseline RLS, and role-aware identity

**Prerequisites:** 2, 3

**Read:** `docs/03-schema.md`, `docs/04-api.md`, `docs/10-security-privacy.md`, `docs/11-testing-quality.md`, `docs/decisions/0006-foundation-auth-and-rls-sequence.md`

Create the non-exposed `app` schema, private helper boundary, and Alembic migrations for `user_account`, `team`, `team_membership`, and `player`, including `season_end_at`. Every protected table ships with baseline RLS policies, safe helpers/grants, and runtime-role positive/negative isolation tests in this task. Bind IDs to `auth.users.id`; the API role neither owns protected tables nor bypasses RLS. Complete role-aware `/v1/me`, membership-dependent authorization, account linkage, and coach/player routing. Provide an operator-only initial coach/team bootstrap; self-signup cannot acquire coach privileges. Unlinked identities get empty roles/teams and no product access.

**Test:** migrate up/down; profile sync; duplicate active jersey/linked player; runtime-role cross-player/cross-team SELECT/INSERT/UPDATE/DELETE denial on every created table; missing/malformed context and pool reset; Data API non-exposure; safe bootstrap; `/v1/me` for coach/player/unlinked identity; revoked membership immediately removes access.

**Done:** protected schema exists locally and in the linked development project with baseline isolation tests mandatory in CI, no second identity UUID, and real database-backed role-aware identity. No unprotected table or role stub is handed off.

### Task 5 — Extend the RLS isolation harness

**Prerequisites:** 4

**Read:** `docs/03-schema.md`, `docs/10-security-privacy.md`

Extend the policies and mandatory runtime-role harness already delivered by Task 4. Add reusable fixtures for future schema tasks, complete the access matrix, mutation checks, pooled-context regressions, and schema/grant/policy snapshots. This task never introduces the first protection for an existing table.

**Test:** two teams, two coaches, at least two players per team; every forbidden read/write is empty, 404, or denied, with positive reads/writes also checked. Removing or broadening a policy makes CI fail.

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

Add judgment and immutable `judgment_revision` schema/API with RLS and runtime-role isolation tests, revision 1 at creation, monotonically increasing versions, mandatory `If-Match`, transactional append on every edit, coach-only history, and session-derived original author. Preserve rejected judgments. Publication/revision/clip pointers and their FKs are introduced in Task 17, when target tables exist; no published state is possible before then.

**Test:** spoofed author rejected; cross-team goal rejected; original-author-only edit; create/edit/no-op/replay versions; stale/concurrent writes; rollback cannot leave a revision gap; ordinary revision update/delete denied; rejected snapshot never publishable.

**Done:** applied, opportunity, and rejected drafts persist correctly.

### Task 16 — Draft preservation and conflict recovery

**Prerequisites:** 15

**Read:** `docs/05-ui.md`, `docs/11-testing-quality.md`

Persist local drafts on every change, reconcile optimistic API writes, restore after reload/offline, and handle stale versions without loss.

**Test:** mark five clips, edit comments, force reload and network failure, then recover all five exactly.

**Done:** draft-preservation test is load-bearing in CI.

### Task 17 — Player-only clip export and batch publish

**Prerequisites:** 10, 15, 16

**Read:** `docs/00-decisions.md`, `docs/02-architecture.md`, `docs/03-schema.md`, `docs/04-api.md`, `docs/10-security-privacy.md`, `docs/11-testing-quality.md`, `docs/decisions/0008-judgment-revisions-and-republication.md`

Add protected `review_publication`, revision-pinned ordered items, evidence clips, and current publication/revision/clip pointers. Implement exact-boundary exports, full-set replacement, player/game and judgment serialization, expected predecessor/version checks, retry/cancel, atomic snapshot swap, and withdrawal. Changed revisions get new objects; unchanged ones may reuse matching ready clips. Players keep the old set through replacement export/failure. Fence withdrawn, expired, and deletion-pending targets; schedule obsolete-object cleanup. Signing lifetimes are at most five minutes for player clips and fifteen minutes for coach playback.

**Test:** 3–6 rule and one-current-set cap; revision/clip matching; draft text hidden at DB/API layers; comment-only edit and republish; concurrent disjoint/overlapping requests; stale predecessor/version; edits during export; retry/cancel; worker restart; old snapshot visibility on failure; atomic replacement; omitted-item withdrawal; withdrawal/export race; exact duration tolerance; expired/obsolete/full-match URL denial.

**Done:** publication survives restart; first visibility waits for every clip; replacement changes text/verdict/media atomically; old sets remain intact on failure; no draft or coach playback leaks to a player.

### Task 18 — Player mobile experience

**Prerequisites:** 17

**Read:** `docs/05-ui.md`, `docs/09-frontend-design-system.md`, `docs/10-security-privacy.md`

Build player home, goal/evidence sequence from current published revisions only, object-specific clip signing with expected revision checks, whole-set refresh on replacement, low-data preload behavior, and safe verdict copy.

**Test:** all player viewports in `docs/09-frontend-design-system.md` plus 375px; keyboard/screen reader basics; Player B cannot read/sign Player A's evidence; publication swap never pairs old text with new media.

**Done:** a linked player opens only their clips on a phone; no full video identifier or URL appears in the response or DOM.

### Task 19 — Optional reflections

**Prerequisites:** 18

**Read:** `docs/03-schema.md`, `docs/04-api.md`, `docs/05-ui.md`, `docs/10-security-privacy.md`, `docs/decisions/0007-author-controlled-reflections.md`

Build one optional author-controlled reflection per judgment with RLS and runtime-role isolation tests. The player can create on current published evidence, edit, and permanently delete; the coach can only read. Provide own-reflection management after evidence withdrawal, saved-version context after republish, and bounded content-free replay/deletion markers. Keep no reflection text history or text in emails/jobs/events. Preserve unsent text through transient failure, clear it after deletion/sign-out, and prevent stale retried saves from resurrecting deleted or superseded content.

**Test:** author CRUD; coach read-only; other-player denial; length/duplicate/skip; save/delete races; retry after deletion; deliberate new create; withdrawn-evidence management; republish context; caches/queued text cleared; no text history.

**Done:** reflection changes reach only the authorized player/coach, permanent active deletion is verified, and optional reflection never gates playback. Backup/restore validation remains Task 22 release acceptance.

### Task 20 — Email delivery

**Prerequisites:** 3, 17, 19

**Read:** `docs/05-ui.md`, `docs/10-security-privacy.md`

Add Resend templates, verified redirect allowlist, one evidence-set email after each successful publication (including replacement), coach video-ready/failure messages, and the reflection daily digest specified in `docs/05-ui.md`. Digest carries only an authenticated link and neutral notice, never reflection text; deletion suppresses stale queued notices. Deduplicate by publication/event identity.

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

Implement all deadlines in `docs/10-security-privacy.md`: failed-upload/processing cleanup, source expiry from upload completion, immutable season cutoff, obsolete/private exports, and product-history expiry. Add shared-footage hard deletion, durable restricted content-free manifests with RLS/tests, worker fencing, account/archive rules, backup deletion replay, safe operational events, and SQL queries for review duration/open rate. Owner confirmation of season, collateral deletion, notice, operator, and actual backup expiry is required before real-data use, not inferred from this task.

**Test:** every deadline boundary and retry clock; two-player shared match with both players' clips; FK-safe deletion of judgments/revisions/reflections; unrelated-data review; deletion during export; no resurrected objects; partial failures; backup restore suppression; no content in logs/events/manifests; idempotent retention.

**Done:** deletion removes all scoped objects and rows, marks any unresolved failures honestly, and restore cannot re-expose erased content; owner-confirmed operational prerequisites are recorded before real-data onboarding.

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

**Prerequisites:** 25, 26 (evaluation go/no-go permits proceeding)

**Read:** `docs/03-schema.md`, `docs/07-cv.md`

Store immutable run metadata, a tracklet index in Postgres, and per-frame trajectories in Parquet. Validate the artifact's declared original-video timestamp timebase; normalize external segment-local output exactly once before accepting the canonical artifact. Implement the Phase D cleanup exception in `docs/07-cv.md`: delete only unreferenced CV observations, retain referenced observations with machine provenance cleared, and keep mandatory judgment FKs intact. Include RLS and isolation tests with the new schema.

**Test:** frozen artifact produces byte-stable semantic rows and Parquet schema; non-zero segment offset is not applied twice; referenced/unreferenced observation cleanup; judgment-creation/deletion race; repeat cleanup; no lost human revision or orphan FK.

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
