# 11 — Testing and quality

## Quality contract

Shoulder is ready only when its highest-risk promises are demonstrated: one player cannot see another player's data, a player cannot retrieve a full match, draft work survives interruption, and published clips accurately represent the coach-selected bounds.

Tests should prove behavior at the lowest useful layer and repeat the critical path end to end. Do not chase coverage percentage while leaving authorization or media boundaries untested.

## Test layers

| Layer | Scope | Typical examples |
|---|---|---|
| Unit | Pure functions and small services | time bounds, candidate rules, job backoff, copy mapping |
| Database | Migrations, constraints, RLS, transactions | cross-player denial, membership revocation, job claims |
| API integration | FastAPI plus real Postgres/MinIO | auth claims, idempotency, signed-object selection, errors |
| Web integration | Next.js routes/components with mocked external edges | session handoff, form states, generated-client use |
| Media integration | Real ffmpeg/ffprobe and fixture videos | fast-start MP4, duration, clip boundaries, range seek |
| End to end | Browser plus production-like services | upload, review, publish, player watch/reflection |
| Manual/visual | Human checks where automation is insufficient | timeline usability, mobile video, responsive polish |

Use small synthetic video fixtures generated for the test suite. Real team footage never enters the repository or ordinary CI.

## Load-bearing suites

These suites block merge and release. They cannot be skipped, marked flaky, or converted to expected failure.

### 1. Isolation matrix

Create fixtures for two teams, two coaches, and at least two players per team. Exercise direct table access through the runtime role and every protected API route.

Verify:

- Player A can read their published goal, judgment, ready clip metadata, and reflection.
- Player A cannot read Player B's equivalent resources, even by known UUID.
- A player cannot read any draft, rejected observation, coach playback metadata, upload, job, or CV artifact.
- Coach A cannot read or mutate Team B.
- Removing a membership takes effect on the next request and database transaction.
- Missing `app.user_id`, malformed UUID context, and an expired JWT fail closed.
- Unauthorized resource IDs do not disclose whether the row exists.
- The Supabase Data API cannot address the `app` schema, and runtime roles have only the intended schema/table/function grants.

### 2. Player media boundary

- A player clip endpoint returns a URL for the current ready `evidence_clip` object only.
- Supplying a video UUID, R2 key, previous clip version, or another player's clip fails.
- A copied/expired URL fails after its lifetime.
- The player page source, logs, and analytics contain no coach playback key or signed URL.
- HTTP Range requests work on a valid player clip without broadening object access.

### 3. Draft durability

- Create five marked moments, reload, and verify exact bounds, order, type, player, and text.
- Interrupt one save and recover without duplicating or losing moments.
- Exercise offline-to-online transition with a visible unsaved state.
- Concurrent edits produce an explicit conflict or version failure, not last-write data loss.
- Closing a dialog or navigating with unsaved text warns the coach.

### 4. Deterministic CV artifact

After Phase D, ingest the frozen fixture twice and verify the same normalized run/track/candidate output. Package/library upgrades must either preserve the artifact or create an explicitly reviewed new artifact version.

## Database testing

For every migration:

- Apply from an empty database.
- Upgrade from the previous released migration.
- Run constraints and RLS tests through the real runtime role.
- Confirm every foreign key has an index or an explicit reason not to.
- Confirm timestamps use `timestamptz`, offsets use integer milliseconds, and bounded fields have checks.
- Confirm policies use indexed columns and do not accidentally evaluate user context per row when a statement-level form is available.
- Confirm `app` is absent from exposed Data API schemas; helpers in `private` have safe search paths and no unintended `PUBLIC`, `anon`, or `authenticated` execution.
- Test rollback in development when the migration is designed to be reversible; otherwise document recovery/forward-fix.

Snapshot the schema, grants, policies, and function security modes in CI for review.

## Authentication and API testing

- Valid, expired, wrong-audience, wrong-issuer, wrong-algorithm, malformed, and revoked/rejected tokens.
- Missing or stale membership after a valid token.
- CSRF/origin failure on state-changing BFF routes.
- Magic-link callback success, reused code, invalid code, refreshed cookie propagation, and safe redirect behavior.
- Logout clears session cookies and protected pages no longer render from cache.
- Every mutating endpoint verifies idempotency where the contract promises it.
- Pagination is stable and bounded.
- RFC 9457 errors expose a safe code, title, status, and request identifier—not a traceback or sensitive value.
- OpenAPI generation is deterministic; the TypeScript client is regenerated and diffed.

## Upload and storage testing

Test 1–3 GB synthetic files outside ordinary unit CI in a controlled integration job.

- Valid multipart upload with configured part size and concurrency.
- Network loss after several complete parts; resume sends only missing parts.
- Tab close pauses; reopening/reselecting the identical file resumes.
- Different file with the same name does not resume the old upload.
- Duplicate complete request is idempotent.
- Aborted, expired, too-large, too-many-parts, wrong-size, corrupt, and unsupported media cases.
- Object key and URL never use a client filename.
- CORS accepts configured origins and rejects unconfigured origins.
- Presigned PUT cannot read and presigned GET cannot write or address another object.

## Media testing

Fixture set should include portrait/rotated video, variable frame rate, no audio, common phone audio, unusual keyframe spacing, non-zero start timestamps, and a corrupt file.

Verify:

- Coach output is H.264/AAC or H.264 without audio, 720p within aspect-ratio rules, fast-start, and seekable by Range.
- Duration stays within an approved tolerance of the source.
- Requested clip start/end are clamped to the source and re-encoded accurately.
- A clip contains no meaningful footage outside the approved privacy tolerance.
- The complete requested set stays hidden until every current clip version is ready, then becomes visible atomically.
- The explicit publication and ordered items survive a worker restart, an idempotent retry reuses them, and a partial failure exposes none of the set.
- Two concurrent publish requests with an overlapping judgment cannot create two active publications or two competing current-clip swaps.
- A replaced judgment produces a new clip version; stale versions are not signed and are eventually deleted.
- Worker timeout, cancellation, crash, heartbeat expiry, retry, and terminal failure leave the original recoverable.

Task 11 must measure a full 90-minute 720p output on normal broadband: first frame, random seek p75, bytes transferred, browser memory, and failure/retry behavior. If the architecture misses its budgets, write an ADR before adding HLS.

## Frontend behavior testing

- Component tests cover visible labels, keyboard behavior, validation, focus return, and state transitions.
- Browser tests use accessible roles/names rather than brittle CSS selectors.
- Critical flows run at the viewport matrix in `09-frontend-design-system.md`.
- Capture visual baselines for sign-in, dashboard, upload, review, publish, player clip, reflection, and their empty/loading/error states.
- Visual diffs are reviewed; they are not blindly updated.
- Test 200% zoom, large text, reduced motion, high contrast where supported, keyboard-only navigation, and screen reader announcements.
- Run automated accessibility checks, then manually test video controls, timeline, dialogs, and player clip navigation.

## Performance testing

Measure at p75 for user experience and p95 for API operations using production-like data.

| Metric | Budget |
|---|---:|
| Player LCP | <= 2.5 s |
| Player INP | <= 200 ms |
| Player CLS | <= 0.1 |
| Player clip first frame on 4G profile | < 2 s |
| Coach first frame on normal broadband | < 2.5 s |
| Coach random seek | < 1.5 s p75 |
| Timeline interactive after video metadata | < 500 ms |
| JSON API excluding cold start | < 300 ms p95 |
| Six clip exports after publish | < 90 s |

Bundle budgets should be set after the first measured shell, then kept explicit per route. Do not load the review timeline/video code on player routes. Fonts are self-hosted and subset. Images define dimensions. No third-party script can enter a critical route without an ADR and measured impact.

## Reliability and concurrency testing

- Two workers claim distinct jobs under contention.
- An expired lease is reclaimed once; a live heartbeat is not stolen.
- Duplicate queue insertion collapses under the deterministic key.
- Publishing twice does not create duplicate visible clips.
- Deleting during transcode or clip export ends in a consistent deleted state.
- Database, R2, email, and worker transient failures retry only safe operations.
- Non-retryable validation failures surface a plain coach-facing recovery path.
- Restore a sanitized database backup and verify object/database reconciliation in a drill.

## CV evaluation testing

After the manual gate:

- Validate manifest and artifact schemas with malformed and version-mismatch fixtures.
- Verify checksums, timestamp normalization, rotation, rational frame rate, and segment offset mapping.
- Evaluate by match, not random nearby frames.
- Report recall, candidate burden, keep rate, tracklet purity, reproducibility, and measured coach time saved.
- Keep raw confidence out of player/product ranking code.
- Confirm deleting a CV run does not delete a coach-authored judgment.

## CI stages

1. Formatting, lint, static types, dependency/secret scan.
2. Unit and component tests.
3. Schema migration, RLS, and API integration against disposable Postgres/MinIO.
4. Media integration with small fixtures.
5. Production build and generated-client drift check.
6. Browser critical path and automated accessibility.
7. Scheduled/explicit large-upload, 90-minute playback, recovery, and CV evaluation jobs.

Fast checks may run in parallel, but a merge result is green only when all required stages for the changed area pass.

## Definition of done for a task

- Acceptance criteria in `06-tasks.md` are met.
- New behavior has positive and negative tests at the appropriate layers.
- Authorization and privacy failure paths are covered.
- Relevant loading, empty, error, retry, and interrupted states are implemented and tested.
- Named commands and their outcomes are recorded in the handoff.
- Generated files are up to date and reproducible.
- Documentation and `STATUS.md` reflect any changed contract.
- No skipped tests, unexplained warnings, secret output, real player data, or unrelated refactor is included.

## Release gates

### Manual MVP release

- Tasks 1–22 complete.
- All four load-bearing suites applicable to the phase pass.
- Security checklist in `10-security-privacy.md` passes.
- Three real games complete the manual loop.
- Coach and player usability checks are documented.
- Retention, deletion, and incident procedures have an owner.

### CV-assisted release

- Manual release remains healthy without CV.
- Tasks 23–30 complete with a frozen artifact.
- External licenses/terms are rechecked.
- Evaluation demonstrates time saved, not merely model activity.
- CV candidate output remains coach-only and neutral.
