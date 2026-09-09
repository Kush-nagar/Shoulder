# Project 02 verification — Video ingest and durable work

Evidence index for the project block covering **Task 8**, **Task 9**, and
**Task 10**. It replaces per-task narrative records for those three tasks.

- Base `main`: `7528259f319a19903fc096bb4b4a0f57860cc3df`
- Branch: `project-02-video-ingest-durable-work`
- Verified: 2026-09-09
- Local stack: Supabase CLI 2.116.0, PostgreSQL 17.6, MinIO
  `RELEASE.2025-09-07T16-13-09Z`
- Remote development project: **not touched by this block**; `Shoulder Dev`
  still runs `0004_roster_goals`. See "Shoulder Dev" below.
- Block contract: `project-02-video-ingest-durable-work.md`

## Scope correction recorded before implementation

The block was requested as "Task 8 R2 client, Task 9 durable job table, Task 10
ffmpeg → HLS". That does not match this repository:

- `docs/06-tasks.md` and `docs/projects/README.md` define Block 02 as Task 8
  (R2 multipart service), Task 9 (honest resumable upload UI), and Task 10
  (durable Postgres worker queue).
- Transcoding is **Task 11**, which the same request placed out of scope.
- HLS is forbidden by `AGENTS.md` rule 8 and
  [ADR 0001](../decisions/0001-progressive-mp4-and-isolated-player-clips.md),
  which defers it until Task 11 measures a 90-minute fixture against the
  playback budgets. Block 03's definition of done reads "no HLS".

The conflict was raised before any code was written and the owner chose the
repository-canonical scope. Nothing in this block transcodes, and no ADR was
overturned.

## Task requirements to evidence

| Task / requirement | Implementation | Test / evidence | Result |
|---|---|---|---|
| **T8** `game`, `video`, `video_upload_part` schema with RLS | `migrations/versions/0005_video_ingest_durable_work.py` | `tests/test_database_video.py` | 36 passed |
| **T8** private bucket configuration | `infra/compose.yaml`, `infra/r2-cors.json` | anonymous GET denied; `test_an_unauthenticated_request_cannot_read_the_bucket` | passed |
| **T8** strict CORS | `MINIO_API_CORS_ALLOW_ORIGIN`, `infra/r2-cors.json` | `test_cors_answers_the_configured_origin_and_no_other` | passed |
| **T8** multipart start / sign / list / complete / abort | `services/api/storage.py`, `services/api/video.py` | `tests/test_storage.py`, `tests/test_api_upload.py` | 25 + 29 passed |
| **T8** object-specific signed GET | `storage.sign_get` | signed GET cannot write, cannot address another object, expires | passed |
| **T8** upload-part persistence | `video.reconcile_parts` | parts come from `ListParts`, never from a client claim | passed |
| **T8** test: 2 GB generated file | `tests/test_large_upload.py` | 2 GB over 64 real parts, 13 s, edges checksum-matched | passed |
| **T8** test: interrupted part | `tests/test_storage.py`, `tests/upload.spec.mjs` | storage keeps the parts it has; the browser resumes | passed |
| **T8** test: repeated complete request | `video.complete_upload` | second call returns the first answer; one job pair | passed |
| **T8** test: wrong object / verb / part | `tests/test_storage.py` | all three refused with 403 by the signature | passed |
| **T8** test: expired URL | `tests/test_storage.py` | 1-second GET refused after expiry; >15 min refused at signing | passed |
| **T8** done: failed parts retry without repeating completed parts | `upload-state` is authoritative | `test_a_resumed_upload_never_repeats_a_completed_part`; browser ETag unchanged | passed |
| **T8** done: video bytes never pass through FastAPI | presigned PUT/GET only | no route reads or writes an object body; browser PUTs go to storage | passed |
| **T9** game metadata | `apps/web/app/coach/upload/new-match.tsx`, `actions.ts` | `tests/upload.spec.mjs` | 9 passed × 3 engines |
| **T9** file validation | `apps/web/lib/upload.ts` `validateFile` | `tests/upload.test.mjs`; browser refuses before signing anything | 26 + 9 passed |
| **T9** three-part concurrency | `upload.ts` `inParallel`, `CONCURRENCY = 3` | `at most three parts are ever in flight` | passed |
| **T9** local resume metadata | `uploader.tsx` `localStorage` hint | reload shows the unfinished upload with name, size, modified time | passed |
| **T9** server reconciliation | `GET /v1/videos/{id}/upload-state` | client sends only `missing_part_numbers` | passed |
| **T9** reselect-same-file recovery | `upload.ts` `sameFile` | same name with different bytes abandons instead of resuming | passed |
| **T9** accurate tab-closure copy | `uploader.tsx` | exact `docs/05-ui.md` strings; "safe to close" absent until complete | passed |
| **T9** test: interrupt, reload, reselect, resume, complete | `tests/upload.spec.mjs` | only parts 2 and 3 re-sent; part 1 ETag unchanged | passed |
| **T9** done: never claims upload continues after tab close | `beforeunload` warning plus the two fixed strings | asserted in the browser suite | passed |
| **T10** job schema | `0005` `app.processing_job` | `tests/test_database_video.py` | passed |
| **T10** idempotency keys | `video.job_key`, unique index | `test_enqueueing_the_same_key_twice_creates_one_job` | passed |
| **T10** claims | `services/worker/jobs.py` `claim` | `FOR UPDATE SKIP LOCKED` against real Postgres | passed |
| **T10** leases and heartbeat | `jobs.heartbeat` | a second worker cannot heartbeat someone else's lease | passed |
| **T10** backoff | `jobs.fail`, `jobs.backoff_seconds` | SQL curve asserted against the Python curve, including the ceiling | passed |
| **T10** cancellation | `jobs.request_cancel` / `cancel_requested` / `cancelled` | cooperative; a finished job cannot be cancelled | passed |
| **T10** terminal failure | `jobs.fail` | last attempt is terminal; error text bounded to 60/300 characters | passed |
| **T10** stuck-job recovery | `jobs.sweep_expired_leases` | recovered once, never twice; exhausted attempts fail honestly | passed |
| **T10** test: two workers, 100 jobs, no double execution | `tests/test_database_queue.py` | 100 claims, 100 distinct ids, `max(attempts) = 1` | passed, 3 consecutive runs |
| **T10** test: crashed lease safely recovered | same | stale completion refused; the next claimant owns it | passed |
| **T10** test: idempotent enqueue creates one job | same | `ON CONFLICT (idempotency_key) DO NOTHING` | passed |
| **T10** done: concurrency test stable across repeated runs | same | three consecutive full-suite runs, all green | passed |

## Shared contracts frozen for this block

- Migration `0005_video_ingest`: `app.game`, `app.video`, `app.video_upload_part`,
  `app.processing_job`; `private.is_game_coach(uuid)`, `private.is_video_coach(uuid)`;
  the `shoulder_worker` role ([ADR 0018](../decisions/0018-worker-database-role.md)).
- Nine coach API routes, all RFC 9457 on failure:
  `POST /v1/games`, `GET /v1/teams/{team_id}/games`, `GET /v1/games/{game_id}`,
  `POST /v1/games/{game_id}/videos/uploads`,
  `POST /v1/videos/{video_id}/upload-parts/sign`,
  `GET /v1/videos/{video_id}/upload-state`,
  `POST /v1/videos/{video_id}/upload-complete`,
  `POST /v1/videos/{video_id}/upload-abort`,
  `GET /v1/videos/{video_id}`.
- Storage constants: 32 MiB parts, 8 GiB ceiling, 256 parts, 15-minute signing.
- Object key `originals/{video_id}/source.{ext}`, derived only from the generated
  id and a three-entry extension allowlist.
- Deterministic job keys `transcode:{video_id}:v1` and `thumbnail:{video_id}:v1`.
- Five same-origin BFF routes under `apps/web/app/api/`, each naming one fixed
  upstream path; there is no pass-through proxy.
- Generated TypeScript types only; no hand-written parallel API types.

## Database

- Revision: `0004_roster_goals` → **`0005_video_ingest`**.
- Tables: `app.game`, `app.video`, `app.video_upload_part`, `app.processing_job`;
  all four `ENABLE` + `FORCE ROW LEVEL SECURITY`, all owned by `shoulder_migration`.
- Functions: `private.is_game_coach(uuid)`, `private.is_video_coach(uuid)`, both
  `SECURITY DEFINER` with `search_path = ''` and fully qualified references.
- Policies: 19 new rows, snapshotted in `tests/test_database_isolation.py`.
  Players appear in none of them: `docs/03-schema.md` gives players no access to
  any of these four tables, so absence is the policy.
- Grants: `shoulder_api` gets table `SELECT` everywhere, table `INSERT` on `game`
  and `video_upload_part`, `DELETE` on `video_upload_part` only, and column-level
  `INSERT`/`UPDATE` elsewhere. `app.video.original_key` and `app.video.id` are
  insert-only with no `UPDATE` grant on either runtime role, so no row can be
  retargeted at another object. `shoulder_worker` gets `SELECT` on
  `processing_job` and `video`, a column-scoped `UPDATE` on each, and no
  `INSERT`, `DELETE`, or `private` execute privilege at all.
- `PUBLIC`, `anon`, and `authenticated` hold no privilege on any new object.
- Upgrade/downgrade: `0004 → 0005 → 0004 → 0005` clean; the full base
  `downgrade → upgrade` cycle in `ZMigrationTests` passes with the table count at
  nine and the `private` function count at eleven.

## Local verification results

| Command | Result |
|---|---|
| `scripts/check.ps1` | Biome format/lint, TypeScript, 26 Node tests, Ruff, strict mypy, 260 Python tests, generated-contract drift, production build, browser-secret scan, 3 smoke tests × 3 engines, `git diff --check` — all passed |
| `scripts/check-db.ps1` | 260 Python tests, 1 skip (the opt-in 2 GB proof), migrations up/down/up, policy-mutation checks |
| `scripts/check-storage.ps1` | 53 storage and upload API tests, the 2 GB multipart proof, bucket empty afterwards |
| `scripts/check-upload.ps1` | 9 browser tests (3 cases × chromium, firefox, webkit) |
| `scripts/check-auth.ps1` | 6 auth browser tests, unchanged and unweakened |
| `scripts/check-roster.ps1` | 9 roster browser tests, unchanged apart from the fixture truncation list |

Exact counts: 260 Python tests (46 new database/queue, 29 upload API, 25
storage, 1 large upload), 26 Node unit tests (11 new), 9 upload browser tests,
9 roster browser tests, 6 auth browser tests, 3 smoke tests.

### The three hard acceptance proofs

1. **2 GB multipart.** `tests/test_large_upload.py` generates a 2 GiB payload in
   the system temporary directory, creates the upload through
   `POST /v1/games/{id}/videos/uploads`, signs and PUTs all 64 parts through the
   real presigned URLs, completes through the real endpoint, and then
   `HeadObject`-checks the length and checksum-compares the first and last 8 MiB
   through a range-read signed GET. Completed in 13 s over 64 parts. No fixture
   is committed; the payload is deleted in cleanup and the bucket is asserted
   empty at the end of the script.
2. **Two workers, one hundred jobs.** `tests/test_database_queue.py` runs two
   worker identities in two threads against real `FOR UPDATE SKIP LOCKED`
   transactions. 100 claims, 100 distinct job ids, every row `succeeded` with
   `attempts = 1`. Stable across three consecutive runs.
3. **Browser resume.** `tests/upload.spec.mjs` uploads a 64 MiB + 4 KiB file in
   three parts, drops every part PUT except part one at the network layer,
   reloads the page, reselects the identical file, and asserts that exactly
   parts two and three are re-sent and that part one's stored ETag is unchanged.

## Independent review before the pull request

Reviewed as a security and reliability reviewer against the full branch diff
from the base SHA, not against the implementation checklist.

| # | Finding | Disposition |
|---|---|---|
| 1 | `complete_upload` marked a size-rejected video `failed` and then raised `Problem` **inside** the transaction, so the terminal state and `first_terminal_failure_at` were rolled back. The row would stay `uploading` forever with a completed object behind it and no deadline for the Task 22 sweeper to measure from. | Fixed: the rejection is flagged, the transaction commits, and the 409 is raised afterwards. Regression test `test_a_stored_object_that_disagrees_with_the_plan_is_rejected` asserts the persisted status, the failure timestamp, cleared upload id, and that a retry neither revives the attempt nor moves the deadline. |
| 2 | A short PUT is caught earlier than expected: `reconcile_parts` records only a part whose stored length matches the plan, so a truncated part is simply missing. My first test asserted the wrong branch. | Corrected rather than weakened. `test_a_short_part_is_never_recorded_and_stays_resumable` asserts the real behaviour, including that re-sending the one part completes the upload. The length guard after assembly is kept as defence in depth and tested separately. |
| 3 | `GET /v1/videos/{id}/upload-state` writes: it reconciles part rows from storage. A GET with a side effect is normally a CSRF concern. | Accepted and documented. The cookie is `SameSite=Lax`, so a cross-site `fetch` carries no session and gets 401; only a top-level navigation carries it, and the only effect is persisting facts already true in storage from caller-controlled-free input. The verb is fixed by `docs/04-api.md`. |
| 4 | `tests/roster.spec.mjs` truncated a table list that `app.game` now references, so the Project 01 browser suite failed on a foreign-key error. | Fixed by extending the truncation list to the new tables. No roster assertion was changed or removed; all 9 roster tests still pass. |
| 5 | A file written through a Windows-default encoding left `tests/test_database.py` non-UTF-8 and several files CRLF against the repository's `.gitattributes` policy. | Fixed: re-encoded to UTF-8 and normalised to LF. `git diff --check` and Ruff both pass. |

Categories checked with no finding: cross-team leakage at the database or API
layer (asserted in both suites), arbitrary object-key access, browser credential
leakage, signing another upload's part, duplicate completion, aborted-upload
reuse, queue double claims, lease theft, transactions held across storage work,
jobs becoming permanently stuck, and error bodies carrying provider text.

## Shoulder Dev

**Not touched.** This block was verified entirely against the local disposable
stack. `Shoulder Dev` still runs `0004_roster_goals` and holds no fixture rows
from this work.

The migration is ready to deploy but has not been, because Block 02 has no
remote-only behaviour to prove: the storage boundary needs a private R2 bucket
and its CORS list, and the owner has not selected a production domain to put in
`infra/r2-cors.json`. Deploying the schema without that would add tables the
remote project cannot yet exercise. `docs/projects/README.md` marks this block
"Remote: yes"; that step is recorded as outstanding rather than skipped, and
belongs with the R2 bucket decision.

## Known risks

- `infra/r2-cors.json` carries a placeholder origin. Applying it unchanged would
  allow no browser origin at all, which fails closed but is not a working
  configuration.
- The `MAX_UPLOAD_BYTES = 8 GiB` ceiling and the 32 MiB part size are set from
  `docs/02-architecture.md` and a 90-minute phone-footage estimate, not from a
  measurement on the coach's real connection. `docs/00-decisions.md` lists the
  part size as an open decision for Task 8; the 2 GB proof establishes that the
  path works, not that 32 MiB is optimal on home Wi-Fi.
- A rejected upload's assembled object is left in the bucket with its video row
  `failed`. Access is removed immediately (no route serves it), and the 24-hour
  deletion in `docs/10-security-privacy.md` is Task 22's sweeper reading
  `first_terminal_failure_at`. Until Task 22 lands, that deletion is manual.
- The worker process has no production handler, so nothing consumes the queue
  yet. Rows enqueued at upload completion wait rather than fail; this is
  deliberate and is the reason the claim query filters on registered kinds.

## Deliberate deferrals

| Deferred | Owner |
|---|---|
| ffprobe, transcode, `playback_key`, `POST /v1/videos/{id}/playback-url` | Task 11 |
| Thumbnail sprites and `GET /v1/videos/{id}/timeline` | Task 12 |
| Coach player and timeline UI | Task 13 |
| `GET/POST /v1/jobs/{job_id}`, `/retry`, `/cancel` coach surfaces | Block 03 |
| Per-player review state on `GET /v1/games/{game_id}` | Block 04 |
| Retention sweepers; this block only persists their deadlines and timestamps | Task 22 |
| Worker Fly configuration and its ffmpeg image | Task 11 |
| `Shoulder Dev` migration, alongside the R2 bucket and CORS decision | outstanding |
