# Project 02 — Video ingest and durable work

# Goal

A coach uploads a full match file directly to private object storage, an interrupted
upload resumes without repeating a completed part, and a durable Postgres job exists for
the work that will process it.

# Included Tasks

- **Task 8 — R2 multipart service** (`docs/06-tasks.md`)
- **Task 9 — Honest resumable upload UI** (`docs/06-tasks.md`)
- **Task 10 — Durable Postgres worker queue** (`docs/06-tasks.md`)

`docs/projects/README.md` fixes this block's membership. Transcoding is **Task 11**
(Block 03) and progressive MP4, not HLS: ADR 0001 and `AGENTS.md` rule 8 defer HLS until
Task 11 measures a 90-minute fixture against the playback budgets.

# Dependencies

`main` at `7528259f319a19903fc096bb4b4a0f57860cc3df` (Block 01 merged, PR #9). This block
consumes, and does not redesign:

- `app.user_account`, `app.team`, `app.team_membership`, `app.player` (`0001`)
- `shoulder_migration` / `shoulder_api` / `shoulder_operator` separation (`0002`, ADR 0016)
- `private.current_user_id()`, `private.is_team_member(uuid)`, `private.is_team_coach(uuid)`
- `private.is_player_coach(uuid)`, `private.is_player_self(uuid)` (`0004`)
- `services/api/db.py` `user_transaction`, `services/api/problems.py` RFC 9457 rendering
- `tests/isolation_fixtures.py` `IsolationHarness` / `World`
- `infra/compose.yaml` MinIO (`shoulder-local` bucket, anonymous access denied)

Current database revision on `main` and on `Shoulder Dev`: `0004_roster_goals`.

# Existing contracts this block must preserve

- Video bytes never pass through FastAPI (`docs/02-architecture.md` constraint 2).
- Buckets stay private; a signed URL names one object, one HTTP verb, and a short expiry.
- The API connects as `shoulder_api` (`NOBYPASSRLS`) and publishes the verified subject
  transaction-locally as `app.user_id`. Authorization is the database's answer.
- Every protected table gets `ENABLE` + `FORCE ROW LEVEL SECURITY`, a
  `shoulder_migration` owner-maintenance policy, and per-command policies where predicates
  differ.
- `PUBLIC`, `anon`, and `authenticated` hold no privilege in `app` or `private`.
- Object keys are generated server-side. A client filename never reaches a key or a path.
- Public TypeScript API types come only from FastAPI's OpenAPI document.
- Retention clocks are server-set once and never extended by a retry
  (`docs/10-security-privacy.md`).

# Frozen block contract

## 1. Migration

One migration, `0005_video_ingest_durable_work`, revising `0004_roster_goals`. Its
downgrade restores the exact `0004` state (tables, roles, policies, and grants).

### `app.game`

`id`, `team_id` (FK `app.team` cascade), `opponent`, `played_at`, `kind`
(`match`|`scrimmage`), `notes`, `created_by`, `created_at`.
Index `(team_id, played_at desc)` and `created_by`.

### `app.video`

Columns per `docs/03-schema.md`: `id`, `game_id`, `original_key`, `playback_key`
(nullable, unused until Task 11), `original_filename`, `content_type`, `size_bytes`,
`sha256`, `multipart_upload_id`, `duration_ms`, `width`, `height`, `fps` (all nullable
until Task 11 probes), `status`, `uploaded_by`, `created_at`, `ready_at`, `deleted_at`,
`upload_completed_at`, `first_terminal_failure_at`, `source_expires_at`,
`derivatives_expires_at`.

`status` ∈ `uploading | uploaded | processing | ready | failed | deletion_pending |
deleted`. Block 02 writes `uploading`, `uploaded`, and `failed` only.
Index `game_id`, `status`, `uploaded_by`, `source_expires_at`, `derivatives_expires_at`.

### `app.video_upload_part`

`video_id`, `part_number`, `etag`, `size_bytes`, `completed_at`; primary key
`(video_id, part_number)`. This is the authoritative resume record; the browser copy is a
cache.

### `app.processing_job`

Columns per `docs/03-schema.md`: `id`, `video_id` (nullable FK), `kind`,
`idempotency_key` (unique), `status`, `available_at`, `attempts`, `max_attempts`,
`progress`, `locked_at`, `locked_by`, `heartbeat_at`, `payload`, `error_code`,
`error_message`, `cancel_requested_at`, `created_at`, `started_at`, `finished_at`.

`kind` ∈ `transcode | thumbnail` in this block. `judgment_id`,
`review_publication_id`, `player_id`, and `cv_run_id` target columns and their kinds
arrive with their owning tables, per `docs/03-schema.md` ("Add later-phase target columns
only when their owning tables are introduced").

`status` ∈ `queued | running | succeeded | failed | cancelled`.
Partial index `(available_at, created_at)` where `status = 'queued'`; index `video_id`.
Checks: `transcode` and `thumbnail` require `video_id`; `attempts <= max_attempts`;
`progress` between 0 and 1; lease columns are all-or-nothing.

### Roles

A fourth role, `shoulder_worker`, is added: `NOBYPASSRLS`, owns nothing, and holds only
the grants a claim loop needs. See ADR 0018.

## 2. Storage boundary

`services/api/storage.py` is the only module that talks to object storage. It wraps the
pinned `boto3` S3 client (see "Dependencies added"). Functions:

| Function | Purpose |
|---|---|
| `create_multipart(key, content_type)` | `CreateMultipartUpload` → upload ID |
| `sign_part(key, upload_id, part_number)` | presigned `UploadPart` PUT, one object/verb/part |
| `list_parts(key, upload_id)` | `ListParts` → `(part_number, etag, size)` |
| `complete_multipart(key, upload_id, parts)` | `CompleteMultipartUpload` |
| `abort_multipart(key, upload_id)` | `AbortMultipartUpload` |
| `head_object(key)` | size and content type confirmation |
| `sign_get(key, seconds)` | presigned object-specific GET |

Constants: `PART_SIZE_BYTES = 32 MiB` (`docs/02-architecture.md`),
`MAX_UPLOAD_BYTES = 8 GiB`, `MAX_PARTS = MAX_UPLOAD_BYTES // PART_SIZE_BYTES = 256`,
`PART_URL_SECONDS = 900`, `GET_URL_SECONDS = 900` (the fifteen-minute coach ceiling in
`docs/10-security-privacy.md`).

Object key: `originals/{video_id}/source.{ext}` where `ext` comes from a server-side
allowlist keyed by the validated extension, never from the submitted filename.

Environment (`R2_*` names follow `docs/02-architecture.md`; MinIO is the local endpoint):
`R2_ENDPOINT_URL`, `R2_BUCKET`, `R2_REGION`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`.

## 3. API surface

Added to `services/api/routes.py`, all coach-authorized through RLS:

| Method | Route | Behavior |
|---|---|---|
| POST | `/v1/games` | Create a game for a coached team |
| GET | `/v1/teams/{team_id}/games` | Cursor list, newest first |
| GET | `/v1/games/{game_id}` | Game plus its video states |
| POST | `/v1/games/{game_id}/videos/uploads` | Filename/size/MIME/sha256 → upload session |
| POST | `/v1/videos/{video_id}/upload-parts/sign` | Part numbers → short-lived PUT URLs |
| GET | `/v1/videos/{video_id}/upload-state` | Server-confirmed parts; authoritative |
| POST | `/v1/videos/{video_id}/upload-complete` | Idempotent completion → job enqueue |
| POST | `/v1/videos/{video_id}/upload-abort` | Abort and mark the attempt terminal |
| GET | `/v1/videos/{video_id}` | Metadata and processing state; no storage keys |

No response contains `original_key`, `playback_key`, `multipart_upload_id`, or a signing
credential. Errors stay RFC 9457 with the existing status table (401/403/404/409/422).

Per-player review state on `GET /v1/games/{game_id}` needs `observation` and `judgment`
(Block 04) and is deliberately absent.

## 4. Upload lifecycle

1. `POST .../videos/uploads` validates extension, declared size, declared MIME, and part
   count, creates the `video` row (`uploading`) and the multipart upload in one path, and
   returns `video_id`, `part_size_bytes`, and `part_count`.
2. The browser asks for a batch of part URLs and PUTs at most three concurrently, direct
   to storage.
3. `video_upload_part` rows are written from `ListParts`, not from a client claim: the
   client sends part numbers, the server reconciles against storage.
4. `GET .../upload-state` returns the server-confirmed part numbers and ETags.
5. `POST .../upload-complete` requires a contiguous `1..part_count` set, completes the
   multipart upload, `HeadObject`-verifies the stored size against the declared size,
   sets `upload_completed_at`, `source_expires_at` (`+90 days`),
   `derivatives_expires_at` (`team.season_end_at + 365 days`), clears
   `multipart_upload_id`, moves the row to `uploaded`, and enqueues the two jobs. A
   repeated call on an already-`uploaded` row returns the same result with `200`.
6. `POST .../upload-abort` aborts the multipart upload, deletes the part rows, and marks
   the row `failed` with `first_terminal_failure_at` set once. See "Block decisions".

## 5. Queue semantics

- Enqueue is idempotent on `idempotency_key`; the deterministic keys are
  `transcode:{video_id}:v1` and `thumbnail:{video_id}:v1`
  (`docs/02-architecture.md`).
- A claim is one short transaction:
  `SELECT ... WHERE status='queued' AND available_at <= now() AND kind = ANY(:kinds)
   ORDER BY available_at, created_at FOR UPDATE SKIP LOCKED LIMIT 1`, then an `UPDATE` to
  `running` with `attempts + 1`, `locked_at`, `locked_by`, `heartbeat_at`, `started_at`.
- `kinds` is the worker's registered handler set. A worker with no handler for a kind
  claims none of it, so an unimplemented kind waits rather than burning attempts.
- Heartbeat updates `heartbeat_at` only while `locked_by` still matches, so a worker that
  lost its lease cannot steal it back.
- The sweeper requeues a lease whose `heartbeat_at` is older than the lease timeout, only
  while `attempts < max_attempts`; otherwise the job becomes `failed`.
- Backoff moves `available_at`; `created_at` is never overloaded.
- Cancellation is cooperative: `cancel_requested_at` is set on the row, the worker checks
  it between stages, and a claimed job it observes on ends `cancelled`.
- Terminal failure records a sanitized `error_code` / `error_message` — no provider text,
  no key, no URL.

## 6. Worker process boundary

`services/worker/main.py` is a separate process connecting as `shoulder_worker`. It has
no HTTP surface and no user identity. Block 02 registers **no** production handler:
Task 11 registers `transcode` and Task 12 registers `thumbnail`. The concurrency suite
registers its own handler, so the loop is proved against real Postgres locking rather
than a mock.

## Dependencies added

`boto3` (pinned) plus its `botocore` graph, in the API and worker runtime.

Why the platform cannot do this safely without it: R2 is reached through the S3 API, and
this block needs both request signing (`CreateMultipartUpload`, `ListParts`,
`CompleteMultipartUpload`, `AbortMultipartUpload`, `HeadObject`) and query-string
presigning for `UploadPart` and `GetObject`. A hand-written AWS SigV4 implementation is
security-critical code with no upstream test suite behind it, and `AGENTS.md` requires the
smallest correct thing rather than a bespoke signer. `boto3` is the reference client for
the S3 API this project already chose.

# Scope

Database: migration `0005`, four tables, their RLS/policies/grants, `shoulder_worker`.

API: the nine routes above, `services/api/storage.py`, and the upload/game/video schemas.

Worker: `services/worker/` claim loop, lease/heartbeat/backoff/sweeper/cancellation.

Web: `/coach/upload` (game selection, file validation, three-part concurrency, resume,
reselect recovery, the exact `docs/05-ui.md` copy), its BFF routes, and the coach shell's
"Upload match" action pointing at it.

Tests: `tests/test_database_video.py`, `tests/test_database_queue.py`,
`tests/test_api_upload.py`, `tests/test_storage.py`, `tests/upload.test.mjs`,
`tests/upload.spec.mjs`, and `scripts/check-storage.ps1` (2 GB proof).

# Out of scope

Owned by later blocks, and deliberately absent here:

- ffprobe/ffmpeg, transcode, `playback_key`, `POST /v1/videos/{id}/playback-url` (Task 11)
- thumbnail sprites and `GET /v1/videos/{id}/timeline` (Task 12)
- the coach player and timeline UI (Task 13)
- `GET/POST /v1/jobs/{job_id}`, `/retry`, `/cancel` — coach-facing job surfaces belong
  with the Block 03 processing screen. Queue-level cancellation and retry are implemented
  and tested at the database layer in this block.
- `observation`, `judgment`, `review_publication`, `evidence_clip`, `player_reflection`,
  `video_segment`, `cv_run`, `player_track`, `product_event`
- the retention sweepers themselves (Task 22). This block only persists the deadlines and
  the first-failure timestamps those sweepers will read.
- HLS, in any form (ADR 0001, `AGENTS.md` rule 8)

# Block decisions

Recorded here rather than as ADRs because each resolves an implementation detail inside an
already-decided contract. The one architectural addition, the worker role, is ADR 0018.

1. **Abort marks the attempt `failed`.** `docs/03-schema.md` lists no `aborted` status.
   An aborted upload has no stored object, so the honest terminal state is `failed` with
   `first_terminal_failure_at` set once; `docs/10-security-privacy.md` gives the abandoned
   upload a seven-day deadline that Task 22's sweeper reads from that timestamp.
2. **Parts are reconciled from storage, never trusted from the client.** The client names
   part numbers; `ListParts` supplies the ETag and size that get persisted. A client
   cannot assert a part it never uploaded.
3. **`MAX_UPLOAD_BYTES = 8 GiB` / `MAX_PARTS = 256`.** `docs/00-decisions.md` leaves the
   32 MiB part size open for Task 8 measurement; the cap is set from that part size and a
   90-minute phone-footage ceiling, and both are single constants to revise.
4. **No production job handler ships in this block.** The claim loop filters on registered
   kinds, so the `transcode` and `thumbnail` rows enqueued at upload completion wait for
   Tasks 11 and 12 instead of failing.

# Verification plan

| Check | Command |
|---|---|
| Repository quality gate | `scripts/check.ps1` |
| Migration up/down, RLS, isolation, queue, upload API | `scripts/check-db.ps1` |
| Storage integration and the 2 GB multipart proof | `scripts/check-storage.ps1` |
| Browser upload, interrupt, reload, reselect, resume | `scripts/check-upload.ps1` |
| Existing auth and roster suites, unweakened | `scripts/check-auth.ps1`, `scripts/check-roster.ps1` |

Definition of done for the block:

- An interrupted upload resumes without repeating a completed part.
- No video byte passes through FastAPI on any path.
- Two workers claim 100 jobs with no double execution, repeatably.
- A crashed lease is recovered once; a live heartbeat is not stolen.
- Idempotent enqueue creates exactly one job.
- Player A, player B, and a coach outside the team are denied every new table and route.
