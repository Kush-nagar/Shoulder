# Project 02 verification — Video ingest and durable work

Evidence index for the project block covering **Task 8**, **Task 9**, and
**Task 10**. It replaces per-task narrative records for those three tasks.

- Base `main`: `7528259f319a19903fc096bb4b4a0f57860cc3df`
- Branch: `project-02-video-ingest-durable-work`
- Verified: 2026-09-09
- Pull request: [#10](https://github.com/Kush-nagar/Shoulder/pull/10)
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
| `scripts/check.ps1` | Biome format/lint, TypeScript, 26 Node tests, Ruff, strict mypy, 286 Python tests, generated-contract drift, production build, browser-secret scan, 3 smoke tests × 3 engines, `git diff --check` — all passed |
| `scripts/check-db.ps1` | 286 Python tests, 1 skip (the opt-in 2 GB proof), migrations up/down/up, policy-mutation checks |
| `scripts/check-storage.ps1` | 66 storage and upload API tests, the 2 GB multipart proof, bucket empty afterwards |
| `scripts/check-upload.ps1` | 9 browser tests (3 cases × chromium, firefox, webkit) |
| `scripts/check-auth.ps1` | 6 auth browser tests, unchanged and unweakened |
| `scripts/check-roster.ps1` | 9 roster browser tests, unchanged apart from the fixture truncation list |

Exact counts: 286 Python tests (36 video schema and isolation, 35 queue, 6
worker loop, 33 upload API, 33 storage, 1 large upload; the remainder are the
unchanged Task 1–7 suites), 26 Node unit tests (11 new), 9 upload browser tests,
9 roster browser tests, 6 auth browser tests, 3 smoke tests. One test skips: the
2 GB proof, which is opt-in and run by `scripts/check-storage.ps1`.

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

Two passes against the full branch diff from the base SHA, not against the
implementation checklist: one by the implementer, one by an independent
reviewer given only `AGENTS.md`, `CLAUDE.md`, the block contract, ADR 0018, and
the diff.

| # | Finding | Disposition |
|---|---|---|
| 1 | `complete_upload` marked a size-rejected video `failed` and then raised `Problem` **inside** the transaction, so the terminal state and `first_terminal_failure_at` were rolled back. The row would stay `uploading` forever with a completed object behind it and no deadline for the Task 22 sweeper to measure from. | Fixed: the rejection is flagged, the transaction commits, and the 409 is raised afterwards. Regression test `test_a_stored_object_that_disagrees_with_the_plan_is_rejected` asserts the persisted status, the failure timestamp, cleared upload id, and that a retry neither revives the attempt nor moves the deadline. |
| 2 | A short PUT is caught earlier than expected: `reconcile_parts` records only a part whose stored length matches the plan, so a truncated part is simply missing. My first test asserted the wrong branch. | Corrected rather than weakened. `test_a_short_part_is_never_recorded_and_stays_resumable` asserts the real behaviour, including that re-sending the one part completes the upload. The length guard after assembly is kept as defence in depth and tested separately. |
| 3 | `GET /v1/videos/{id}/upload-state` writes: it reconciles part rows from storage. A GET with a side effect is normally a CSRF concern. | Accepted and documented. The cookie is `SameSite=Lax`, so a cross-site `fetch` carries no session and gets 401; only a top-level navigation carries it, and the only effect is persisting facts already true in storage from caller-controlled-free input. The verb is fixed by `docs/04-api.md`. |
| 4 | `tests/roster.spec.mjs` truncated a table list that `app.game` now references, so the Project 01 browser suite failed on a foreign-key error. | Fixed by extending the truncation list to the new tables. No roster assertion was changed or removed; all 9 roster tests still pass. |
| 5 | A file written through a Windows-default encoding left `tests/test_database.py` non-UTF-8 and several files CRLF against the repository's `.gitattributes` policy. | Fixed: re-encoded to UTF-8 and normalised to LF. `git diff --check` and Ruff both pass. |

| 6 | **A shutdown mid-job was recorded as `cancelled`.** `keep_going()` returns False for a shutdown, a cancellation, and a lost lease alike, and `execute` had one outcome for all three. A rolling deploy would leave a video terminally `cancelled` that nobody asked to cancel, never retried. | Fixed: `Worker.stopped_early` reads `cancel_requested_at` and only an explicit cancellation is terminal; anything else calls the new `jobs.release`, which requeues without recording a failure. A handler that returns instead of raising after a shutdown is also released rather than called a success. `tests/test_worker_loop.py` covers all four outcomes. |
| 7 | **A concurrent second completion returned 503.** The loser's `complete_multipart` hit an upload storage had already finished, and the resulting `StorageError` surfaced as "Match storage could not be reached" for an upload that in fact succeeded. | Fixed: `assemble` treats a refusal whose object is nonetheless present as the other request's success and reports the stored length, so the loser falls through to the conditional UPDATE and returns the winner's answer. |
| 8 | **An abort winning the completion race produced a bare 500.** The conditional UPDATE returned no row, and building `UploadCompleted` from an aborted row raised a Pydantic error — no RFC 9457 body, contrary to the block contract. | Fixed: `settled_response` returns the completion only when the row really is `uploaded`, and otherwise raises the `upload-not-open` 409. |
| 9 | **The user transaction was held across two R2 round trips**, locking up to 256 freshly written part rows while storage assembled a multi-gigabyte object, against a 5+5 connection pool. | Fixed: completion is now three phases — authorize and reconcile, then talk to storage holding no transaction, then transition and enqueue in a second short transaction that authorizes again. |
| 10 | **An unhandled kind burned an attempt.** `jobs.fail` incremented its way toward terminal failure, contradicting block decision 4. | Fixed: `jobs.release(..., keep_attempt=False)` hands the attempt back, since nothing ran. |
| 11 | **The sweeper requeued with a flat 30-second delay**, so a crashing worker retried faster than one that reported an error, and it had no index: the partial index is on `status='queued'`, while the sweep scans `status='running'` across a table whose terminal rows are retained. | Fixed: the sweeper uses the same backoff curve as `fail`, and migration `0005` adds `processing_job_leased_idx`, partial on `status='running'`. |
| 12 | **The sweeper stamped `error_code='lease_expired'` on rows it merely requeued**, so the Block 03 coach surface would read "waiting to retry" as "failed". | Fixed: the error columns are set only when the job actually gives up. |
| 13 | **A `StorageError` chained its botocore cause**, whose message names the bucket and the object key. `logging.exception` in the worker would print the whole chain, which `docs/10-security-privacy.md` forbids. | Fixed: the chain is severed with `raise ... from None` and only the short provider code (`NoSuchUpload`, `InvalidPart`) is logged. `tests/test_storage.py` formats the traceback and asserts no key appears in it. |

Categories checked with no finding: cross-team leakage at the database or API
layer (asserted in both suites), arbitrary object-key access, browser credential
leakage, signing another upload's part, aborted-upload reuse, queue double
claims, lease theft, CSRF handling on the new BFF routes, tests that pass
without exercising the real path, and error bodies carrying provider text.

## Automated review on the pull request

GitHub Copilot and Cursor Bugbot reviewed commit `c12dd5d`, before the first
round of fixes was pushed. Four distinct findings, two of them reported by both:

| # | Finding | Disposition |
|---|---|---|
| 14 | **A MOV whose browser reports no type was refused.** Safari and several Windows builds send an empty `File.type` for `.mov`; the client defaulted to `video/mp4` and the server then rejected it as contradicting the extension. A valid match file was refused for saying nothing at all. | Fixed at the boundary the documents name. `docs/04-api.md` says "do not trust the request's MIME type", so `storage.declared_media` now resolves the stored type from the validated extension: an absent or generic type is accepted, a type that positively contradicts the extension is still refused, and the canonical type is what gets stored. The client sends `file.type` verbatim, empty included, instead of guessing. Covered by `DeclaredMediaTests` and an API case for both empty and `application/octet-stream`. |
| 15 | **An assembled upload could become unfinishable.** Bugbot flagged the same window as finding 9, plus a residual: a fault between assembling the object and committing the transition left the row `uploading` with an upload id storage had discarded. Completion then failed on `ListParts` and abort re-raised because the object existed, so the coach could neither finish nor abandon it, and no cleanup deadline was ever set. | Fixed on both halves. `already_assembled` recognises a finished object and completes from it, making completion self-healing; `abort_multipart` now decides whether the failure is real by asking for the upload's parts rather than by looking for the object, so an assembled attempt can still be abandoned. Two API regression tests cover finishing and abandoning from that state. |
| 16 | **`restore_login_passwords` parsed `str(None)`.** A suite configured with only the three original URLs would raise inside `make_url` before the guard that was meant to skip it. | Fixed with a falsy check before parsing. |
| 17 | **`fetchGames` ignored `next_cursor`**, so a `?game=` link to a match older than the first fifty would show "Choose a match". | Fixed by resolving a selected match that is not in the list through `GET /v1/games/{game_id}`. Pagination UI is still not built: one team and one season is the MVP scope (`docs/00-decisions.md` D10), and the fallback removes the defect without it. |

Bugbot reviewed the fixes and raised two more, both high and both real:

| # | Finding | Disposition |
|---|---|---|
| 18 | **A release on the last attempt stranded the job.** `release` requeued without regard to `max_attempts`, so a graceful stop on the final claim left the row `queued` at `attempts = max_attempts`; the next claim's `attempts + 1` violated `processing_job_attempts_bounded`, and that `IntegrityError` is not a `QueueError`, so the worker process died and the job became permanently unclaimable. | Fixed by settling what `attempts` counts: attempts that reached a conclusion. A release hands its attempt back, so a clean shutdown cannot exhaust a job, while a worker that dies instead of releasing is still bounded because `sweep_expired_leases` keeps the attempt. `claim` also gained an `attempts < max_attempts` guard, so no row can ever be claimed into a check violation. Two regression tests: releasing the last attempt leaves the job claimable, and an exhausted queued row is never claimed. |
| 19 | **`upload-state` still failed in the assembled-but-uncommitted window.** Completion and abort were fixed in finding 15, but the resume screen also lists parts, so it kept returning 503 for an upload the coach could in fact finish. | Fixed by moving the recognition into one `survey` call that every route shares — it returns either the parts or "already assembled", and still raises on a genuine outage because `head_object` fails too. That also halves the storage calls per request. `upload-state` reports nothing missing once the object is assembled, rather than asking for bytes storage already holds. |

A third pass on those fixes raised one more:

| # | Finding | Disposition |
|---|---|---|
| 20 | **Abort read an outage as success.** Finding 15's fix decided whether an abort failure was real by asking for the upload's parts — but during an outage that call fails too, so abort would report the attempt abandoned while the multipart upload kept accruing storage. | Fixed by giving `StorageError` the provider's short error code, which names no bucket and no key and is therefore safe to carry. Abort now treats only `NoSuchUpload` and its siblings as "already gone" and re-raises everything else; `survey` and `assemble` use the same discriminator instead of inferring absence from a second failing call. Two tests: a simulated outage surfaces, and an absent upload reports a code that says so. |
| 21 | **The browser resume test raced its own upload.** `inParallel` rejects as soon as one part is refused, so the component surfaced the failure while part one's PUT was still settling, and the assertion read the server too early. Product behaviour was correct; the test was not. | Fixed by polling the authoritative `upload-state` until it reports the part, rather than reading it once. The assertion is unchanged in strength. |

One observation left unchanged: `read_game`, `list_games`, `sign_upload_parts`,
and `read_video` have no `except DBAPIError`, so a database fault there yields a
bare 500 rather than a problem document. The pre-existing roster GETs behave
identically; changing it is a service-wide question, not a Block 02 defect.

## Shoulder Dev

`docs/projects/README.md` marks this block "Remote: yes", so migration `0005`
was deployed to `Shoulder Dev` (`gzbwlancwxhtausyokxt`, PostgreSQL 17) through
the repository Alembic workflow, never the dashboard. Pre-deployment revision
was `0004_roster_goals` with zero drift and none of the four Block 02 tables
present. The project was not downgraded; reversibility is proven locally.

| Check | Result |
|---|---|
| Revision before / after | `0004_roster_goals` → **`0005_video_ingest`** |
| `app` tables | 5 → **9** |
| `private` functions | 9 → **11** |
| Policies on `app` | 15 → **34** (the 19 this block adds) |
| Tables with RLS enabled **and** forced | **9 of 9** |
| Policy predicates on the four new tables | match the local snapshot exactly, all 19 |
| `shoulder_worker` role | present, `NOBYPASSRLS`, not superuser |
| `anon`, `authenticated`, `PUBLIC` grants on the new tables | **0** |
| `shoulder_api` column grants | `video` INSERT includes `id`/`original_key`, UPDATE excludes both; no DELETE anywhere; no UPDATE on `processing_job` |
| `shoulder_worker` column grants | `SELECT` + column-scoped `UPDATE` only; no `INSERT`, no `DELETE`, no `playback_key`, no `private` execute |
| `processing_job` indexes | 5, including the claim and lease partial indexes |
| Fixture rows created by this verification | **0** |

The Supabase MCP role was refused `SET ROLE shoulder_api` with `42501`, which
is the correct answer: the management path cannot impersonate the runtime role
even to run a test.

### One remote check that could not run, and why

The behavioural isolation suites were not run against `Shoulder Dev` on this
pass. `db.gzbwlancwxhtausyokxt.supabase.co` resolves IPv6-only
(`2600:1f10:4d85:4400::daa0`) and this workstation's IPv6 path to it went down
between the migration and the suite run: Alembic connected successfully, and
minutes later `Test-NetConnection` to port 5432 failed twice. That is a network
condition on this machine, not a product or schema defect, and nothing about it
is specific to Block 02.

What that leaves: every structural property above is verified on the remote,
and the behavioural properties those policies produce are verified locally
against the same migration by 286 tests. The gap is behavioural confirmation
*on the remote host*. It is retryable at any time with
`tests.test_database_video`, `tests.test_database_queue`,
`tests.test_worker_loop`, and `tests.test_database_isolation` pointed at the
remote URLs once IPv6 reaches the host, and it needs a `shoulder_worker`
password provisioned for that run. It is recorded here as an open item rather
than quietly omitted.

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
