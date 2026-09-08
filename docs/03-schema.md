# 03 — Database contract

Postgres 17 ([ADR 0015](decisions/0015-postgres-major-version-contract.md)).
Product tables live in a non-exposed `app` schema; narrowly scoped helpers live in `private`. Every change is an Alembic migration. Every foreign key is indexed. All timestamps are `timestamptz`. All media offsets are non-negative integer milliseconds relative to the original uploaded file and use the `*_ms` suffix.

This document is a schema contract, not a migration script.

## Identity and authorization context

`user_account.id` is the Supabase Auth subject UUID and references `auth.users(id)`. Do not generate a second application identity.

FastAPI validates the bearer JWT, starts a transaction, and sets `app.user_id` transaction-locally. Policies use a stable helper in the `private` schema that returns `current_setting('app.user_id', true)::uuid`. The API connects as a dedicated `NOBYPASSRLS` role with an explicit search path. Test that the role does not own protected tables, cannot disable RLS, and has no Data API-facing grants.

Do not use `user_metadata` for authorization. Team roles come from `team_membership`.

Task 3 validates session identity only. Task 4 creates the four core tables (`user_account`, `team`, `team_membership`, `player`) together with baseline RLS, runtime-role isolation tests, and role-aware `/v1/me`; Task 5 extends that harness. Later tables arrive in their owning tasks with the same protection. The initial coach/team membership is created through a documented, restricted operator bootstrap transaction, never from signup metadata. An authenticated but unlinked account has no product permissions. See `docs/decisions/0006-foundation-auth-and-rls-sequence.md`.

## Entity relationship

```text
auth.users ──1 user_account
                   │
                   └──< team_membership >── team ──< game ──< video
                                                │               │
                                                │               ├──< video_segment ──< cv_run ──< player_track
                                                │               │
                                                └──< player ──< development_goal
                                                        │               │
video ──< observation >─────────────────────────────────┘               │
             │                                                          │
             └──< judgment >────────────────────────────────────────────┘
                      ├──< review_publication_item >── review_publication
                      ├──< evidence_clip
                      ├──< judgment_revision
                      └──1 player_reflection
```

## Identity tables

### `user_account`

| Column | Type | Rules |
|---|---|---|
| `id` | uuid | PK; FK to `auth.users(id)`; no default |
| `email` | text | non-null; unique normalized email; synchronized from Auth |
| `display_name` | text | non-null; 1–80 characters |
| `created_at` | timestamptz | non-null; default now |
| `updated_at` | timestamptz | non-null; default now |

The Auth-to-profile synchronization function lives in `private`, sets `search_path = ''`, qualifies every referenced object, and must not copy authorization data from editable metadata. Revoke default `PUBLIC`, `anon`, and `authenticated` execution; grant only the trigger/runtime path that actually needs it.

### `team`

| Column | Type | Rules |
|---|---|---|
| `id` | uuid | PK |
| `name` | text | non-null; 1–100 characters |
| `age_group` | text | optional; 1–40 characters |
| `season_label` | text | non-null; 1–60 characters |
| `season_end_at` | timestamptz | non-null owner-confirmed end of this workspace's season; retention deadline is +365 days |
| `created_by` | uuid | non-null FK `user_account` |
| `created_at` | timestamptz | non-null |

### `team_membership`

| Column | Type | Rules |
|---|---|---|
| `team_id` | uuid | PK part; FK `team` cascade delete |
| `user_id` | uuid | PK part; FK `user_account` cascade delete |
| `role` | text | `coach` or `player` |
| `created_at` | timestamptz | non-null |

Index `user_id`. A player invitation links `player.user_id` and creates the matching player membership in one transaction.

The initial workspace represents one season. Once product data exists, `season_end_at` cannot be extended; shortening requires an explicit operator impact review. Membership changes never grant the user the ability to extend retention.

### `player`

| Column | Type | Rules |
|---|---|---|
| `id` | uuid | PK |
| `team_id` | uuid | non-null FK `team` cascade delete |
| `display_name` | text | non-null; 1–80 characters |
| `jersey_number` | smallint | optional; 0–99 |
| `position` | text | optional; 1–40 characters |
| `user_id` | uuid | nullable FK `user_account`; intentionally nullable |
| `active` | boolean | non-null; default true |
| `created_at` | timestamptz | non-null |
| `deleted_at` | timestamptz | nullable |
| `deletion_pending_at` | timestamptz | nullable; blocks normal access and delayed publication |

Indexes: `team_id`; partial unique active jersey per team; partial unique `(team_id, user_id)` when `user_id` is not null.

The coach can build a roster before collecting any player's email. Linking an account is a separate explicit action.

## Games, media, and work

### `game`

`id`, `team_id`, `opponent`, `played_at`, `kind`, `notes`, `created_at`. `kind` is `match` or `scrimmage` in the MVP. Index `(team_id, played_at desc)`.

### `video`

| Column | Purpose |
|---|---|
| `id`, `game_id` | identity and ownership |
| `original_key` | private raw object |
| `playback_key` | nullable coach-only 720p object |
| `original_filename` | display only; strip path data |
| `content_type`, `size_bytes`, `sha256` | validation and resume matching |
| `multipart_upload_id` | nullable operational state; never returned after completion |
| `duration_ms`, `width`, `height`, `fps` | probed metadata |
| `status` | `uploading`, `uploaded`, `processing`, `ready`, `failed`, `deletion_pending`, `deleted` |
| `uploaded_by`, `created_at`, `ready_at`, `deleted_at` | audit and lifecycle |
| `upload_completed_at`, `first_terminal_failure_at` | nullable until applicable; server-set once, never reset by retry |
| `source_expires_at`, `derivatives_expires_at` | persisted deadlines from `docs/10-security-privacy.md`; never extended by retries |

Indexes: `game_id`, `status`, and expiry deadlines. The state machine rejects backward transitions except explicit retry from `failed` to `processing` before expiry. At an expiry deadline the resource becomes inaccessible; deletion failures are retried and alerted, never reported as completion. Deletion-pending/deleted targets cannot be retried or published.

### `video_upload_part`

`video_id`, `part_number`, `etag`, `size_bytes`, `completed_at`; primary key `(video_id, part_number)`. This is the authoritative resume record. The browser copy is only a cache.

### `video_segment`

`id`, `video_id`, `t_start_ms`, `t_end_ms`, `label`, `created_at`; check end greater than start; unique `(video_id, t_start_ms, t_end_ms)`.

### `processing_job`

| Column | Rules |
|---|---|
| `id` | uuid PK |
| `video_id` | nullable FK video; required for transcode, thumbnail, and video-retention jobs |
| `judgment_id` | nullable FK judgment; required for clip export |
| `review_publication_id` | nullable FK review publication; required with judgment for clip export |
| `player_id` | nullable FK player; required for player-data deletion |
| `cv_run_id` | nullable FK cv_run; required for CV ingest after Phase D |
| `kind` | `transcode`, `thumbnail`, `clip_export`, `video_retention_delete`, `player_data_delete`, `cv_ingest` |
| `idempotency_key` | non-null unique |
| `status` | `queued`, `running`, `succeeded`, `failed`, `cancelled` |
| `available_at` | eligible claim time |
| `attempts`, `max_attempts` | bounded non-negative integers |
| `progress` | numeric from 0 through 1 |
| `locked_at`, `locked_by`, `heartbeat_at` | lease state |
| `payload` | validated JSON object; no secrets or signed URLs |
| `error_code`, `error_message` | sanitized coach-safe failure data |
| `created_at`, `started_at`, `finished_at` | timestamps |

Partial index `(available_at, created_at)` where status is queued. Index every nullable target FK. Checks require the target columns appropriate to the job kind and forbid unrelated targets; a clip export requires both its judgment and publication. Add later-phase target columns only when their owning tables are introduced.

## Product tables

### `development_goal`

`id`, `player_id`, `title`, `description`, optional `ontology_key`, `status`, `created_by`, `created_at`, `closed_at`.

- Status: `active`, `achieved`, `paused`, `retired`.
- Title: 1–100 characters; description: maximum 1,000.
- Partial unique index allows only one active goal per player in the MVP.
- `ontology_key` never changes what a player can read; it only routes future candidate retrieval.

### `observation`

| Column | Rules |
|---|---|
| `id`, `video_id` | identity and media source |
| `segment_id` | optional segment source |
| `player_id` | non-null player being reviewed |
| `t_start_ms`, `t_end_ms` | non-negative; end greater than start; within video duration in service validation |
| `source` | `coach_manual`, `cv_candidate`, `player_flagged` |
| `event_type` | nullable controlled vocabulary |
| `cv_run_id` | nullable; required only for CV candidate |
| `cv_confidence` | nullable; 0 through 1; coach-only |
| `cv_features` | nullable bounded JSON; no embeddings |
| `created_by` | nullable only for system-generated CV candidates |
| `created_at` | non-null |

Indexes: `(video_id, player_id, t_start_ms)` and `(video_id, source)`. Observation rows are append-only in ordinary use; governed erasure and the Phase D provenance exception below are allowed. A rejected candidate remains for later precision measurement only within its retention deadline.

### `judgment`

| Column | Rules |
|---|---|
| `id` | uuid PK |
| `observation_id` | non-null FK observation, `ON DELETE RESTRICT`; stable after creation |
| `goal_id` | non-null FK development goal |
| `author_user_id` | non-null FK user account; server-derived only |
| `version` | bigint, positive; starts at 1; latest content revision, increments by exactly one per accepted edit |
| `publication_status` | `draft`, `published`, `withdrawn`; export/failure belongs to `review_publication`, not this visibility field |
| `current_publication_id` | nullable FK review publication; server-managed |
| `current_revision_id` | nullable FK judgment revision; exact player-visible snapshot |
| `current_clip_id` | nullable unique FK to the current ready `evidence_clip`; server-managed |
| `published_at`, `updated_at`, `created_at` | timestamps |

Unique `(observation_id, goal_id)`. Index `(goal_id, published_at desc)` and every FK. `goal_id`, observation, and author cannot be retargeted by edit. A deferred constraint/transactional write ensures `(id, version)` resolves to the latest immutable revision. All three current pointers are non-null exactly when `publication_status='published'`; otherwise they are null. Add publication/clip FKs only in Task 17, after the target tables exist.

### `judgment_revision`

`id` (UUID PK), `judgment_id` (non-null FK), `version` (positive bigint), `author_user_id` (non-null FK, session-derived original author), `verdict`, `comment_text`, `clip_start_ms`, `clip_end_ms`, `created_at`. Unique `(judgment_id, version)`; index all FKs. Verdict is `applied`, `opportunity`, or `not_relevant`; draft comment may be null, otherwise 1–400 characters. Bounds are non-negative integer milliseconds, end greater than start and inside source duration. Publishing requires a non-empty comment and valid bounds.

Creation writes judgment and revision 1 atomically. Every content-changing edit locks the judgment, checks `If-Match`, increments `version`, and inserts a full snapshot in one transaction; no-op/replayed saves create no new revision. The original author must still coach the team. Ordinary roles cannot update/delete revision rows or change identity/version fields directly; a narrow transactional write path enforces these invariants in addition to RLS. System publication-pointer transitions do not constitute content edits. Verified retention/erasure may delete history; no reflection text belongs in it.

Players may SELECT only the revision named by an accessible judgment's `current_revision_id`. Latest draft text/verdict/bounds must not be duplicated on the player-readable `judgment` row. An old published `applied` revision can remain visible while the latest coach draft is `not_relevant`; the published pointer must never name a `not_relevant` revision. Test both direct runtime-role access and DTO projection.

### `evidence_clip`

`id`, `judgment_id`, `judgment_revision_id`, `version`, `storage_key`, `duration_ms`, `size_bytes`, `sha256`, `status`, `created_at`, `ready_at`, `deleted_at`. Revision FK is non-null and indexed; it must belong to the same judgment. Status is `pending`, `ready`, `failed`, or `deleted`.

- Unique `(judgment_id, version)`.
- At most one current version, selected only by `judgment.current_clip_id` after the related publication succeeds.
- Storage key is returned only through an authorized signing service; never directly in player DTOs.
- Clip version is distinct from judgment version and never reused for different bytes/revisions. A changed revision always gets a new isolated object, including comment-only changes; an unchanged revision may reuse its matching ready clip.

### `review_publication`

| Column | Rules |
|---|---|
| `id` | uuid PK |
| `game_id`, `player_id`, `goal_id` | non-null FKs; the service verifies one consistent review context |
| `requested_by` | non-null FK `user_account`; server-derived |
| `idempotency_key` | non-null unique |
| `status` | `exporting`, `published`, `failed`, `cancelled`, `superseded`, `withdrawn` |
| `replaces_publication_id` | nullable indexed self-FK; must equal the current publication for a replacement |
| `first_terminal_failure_at`, `cancelled_at`, `private_exports_expires_at` | server-set cleanup clocks; retries never extend the deadline |
| `requested_count` | smallint; check 3 through 6 |
| `created_at`, `updated_at`, `published_at` | timestamps |

Index `(player_id, published_at desc)` and `(game_id, player_id)`. Partial unique indexes on `(game_id, player_id)` separately permit at most one `published` and one `exporting` row. A failed item makes the new publication `failed`; the old published set remains unchanged. Retain recoverable private exports only until their cleanup deadline. Replaying the same idempotency key returns this row; payload mismatch returns 409.

Lock the player/game context and affected judgments in a deterministic order. Reserve the requested revisions while exporting: content edits return 409 until failure, cancellation, or completion. Retry must reacquire these locks, verify no conflicting request and that pinned versions are still latest, and preserve the pinned revisions; otherwise return 409 and require a new request. At finalization revalidate membership, active goal, deadlines, withdrawal/deletion state, and the expected predecessor publication. A concurrent withdrawal cancels any pending replacement and invalidates finalization, including retries of previously failed requests.

One transaction marks the predecessor `superseded`, clears current pointers on omitted judgments, sets omitted judgments to `withdrawn`, switches retained/new judgments to their requested revision/clip/publication, and marks the new publication `published`. Until then the old set remains the only player-visible set. The first publication has no old set and stays invisible until ready. Single-judgment withdrawal clears its pointers immediately and leaves remaining items visible; when none remain the publication is `withdrawn`. In that same locked transaction, mark every exporting or retryable failed request for this player/game `cancelled`; old retries cannot restore access. Withdrawal may reduce visible count below three; every new/replacement request still contains 3–6. A replacement after all items are withdrawn has no current predecessor. See ADR 0008 in `docs/decisions/0008-judgment-revisions-and-republication.md`.

### `review_publication_item`

`publication_id`, `judgment_id`, `judgment_revision_id`, `ordinal`, `requested_clip_version`, nullable `evidence_clip_id`, `created_at`, `updated_at`. Revision is a non-null indexed FK; it pins the complete requested snapshot.

- Primary key `(publication_id, judgment_id)`.
- Unique `(publication_id, ordinal)` with ordinal bounded from 1 through 6.
- `evidence_clip_id` is set only after checksum and boundary validation succeed.
- The evidence clip must belong to the same judgment, pinned revision, and requested clip version; enforce transactionally and test it.
- Items are immutable except for attaching a verified matching clip during export/retry. A retry cannot change revision, order, or requested version; changing the set requires cancellation and a new request.
- A judgment may belong to only one nonterminal (`exporting`) publication at a time. Enforce this with a transaction-level advisory lock or equivalent database-backed serialization keyed by judgment ID; do not rely on an in-process mutex.

### `player_reflection`

`id`, `judgment_id`, `player_id`, `text`, `judgment_version_at_save`, `created_at`, `updated_at`; unique `judgment_id`; text 1–1,000 characters; saved version is a positive bigint, server-derived from the visible revision. Index every FK. The service verifies that the authenticated player's linked `player.id` matches the judgment's goal owner. Only that player creates/edits/deletes; coaches read only. Identity fields cannot be retargeted. Creation requires current visible evidence; existing rows remain author-readable/editable/deletable after withdrawal while the account retains access. When editing without current evidence, retain the last saved version marker.

Text is replaced in place with no text history. Permanent deletion removes the active row plus caches and queued copies; record only a content-free deletion/replay marker. Every save requires an idempotency key, a request creation timestamp no older than seven days, and the expected existing reflection ID/row ETag (or explicit create intent). An edit to a missing ID fails; it never becomes a create. Serialize save/delete so an old retry cannot resurrect a removed reflection; a deliberate new create uses a new key and requires visible evidence. Superseded saves likewise cannot overwrite newer text. See `docs/decisions/0007-author-controlled-reflections.md` and backup limits in `docs/10-security-privacy.md`.

## Deferred CV tables

### `cv_run`

`id`, `segment_id`, `pipeline`, `pipeline_version`, `artifact_key`, `artifact_sha256`, `gpu_seconds`, `notes`, `ingested_at`. Unique artifact checksum per pipeline version.

### `player_track`

`id`, `cv_run_id`, `track_ref`, `t_start_ms`, `t_end_ms`, `role`, `team_side`, advisory jersey fields, nullable coach-assigned `player_id`; unique `(cv_run_id, track_ref)`. No appearance embedding columns.

Per-frame trajectories stay in Parquet in R2.

The Phase D deletion exception is specified only for later implementation in `docs/07-cv.md` and ADR 0011. It retains referenced observations with cleared machine provenance; it never makes `judgment.observation_id` nullable. No CV schema is introduced during Tasks 1–22.

## Operational event table

`product_event` records a small allowlist: review started, clip marked, draft saved, publish requested, clip ready, player opened, reflection saved, and reflection removed. It stores pseudonymous IDs and durations, not names, comments, JWTs, URLs, filenames, user agents, or arbitrary payloads. Retain for 180 days.

## RLS access matrix

| Table | Coach | Player |
|---|---|---|
| `user_account` | self; limited linked roster display through safe query | self only |
| `team`, `team_membership` | own coached teams | own membership and team label |
| `player` | players on coached teams | own linked row only |
| `game` | coached teams | no direct access |
| `video`, `video_upload_part`, `video_segment`, `processing_job` | coached teams | no access |
| `development_goal` | coached-team CRUD | own goals read-only |
| `observation` | coached-team read/append; deletion only through governed cleanup | no access |
| `judgment` | coached-team read; original author content edits through revision write path | own currently published identity/pointer rows read-only |
| `judgment_revision` | coached-team read; original author append through transactional write path; no ordinary update/delete | only the exact current published revision of own judgment |
| `review_publication`, `review_publication_item` | coached-team service state machine | own current published set/items whose judgment pointers still select them |
| `evidence_clip` | coached teams | only own current ready clip matching current published revision/item |
| `player_reflection` | coached teams read only; no insert/update/delete | own insert on visible evidence; own read/update/delete including after withdrawal |
| `cv_run`, `player_track` | coached teams | no access |
| `product_event` | service-only writes; limited operator reads | no direct access |

Use separate SELECT, INSERT, UPDATE, and DELETE policies when their predicates differ. UPDATE requires both `USING` and `WITH CHECK`. Enable and force RLS on protected application tables, and test through the same database role used in production.

Reflection UPDATE needs an owner SELECT policy and `USING`/`WITH CHECK`; server-derived player/judgment identity cannot change. Any view projecting published revisions must be security-invoker and preserve underlying RLS. Restricted content-free replay/deletion manifests also contain player/event data: their owning task must provide RLS and isolation tests, with no ordinary player or coach access. Narrow cleanup privileges do not grant general history editing.

## Invariants enforced in service and test

Some cross-table rules cannot be a simple check constraint and must be transactionally enforced:

- Judgment goal and observation belong to the same player.
- Observation player belongs to the video's game team.
- Clip boundaries remain inside video duration.
- No more than six judgments per player/game are current and visible; historical superseded publications are not additional evidence.
- A publication contains exactly 3–6 distinct judgments from the same player, game, and active goal.
- Concurrent requests cannot place the same judgment in two nonterminal publications.
- A judgment becomes published only when every item in its explicit publication is attached to a ready evidence clip matching its pinned human revision. Every current publication/revision/clip pointer must resolve to the same judgment and requested item; validate transactionally and test cross-judgment pointer spoofing.
- One transaction switches all current revision/clip/publication pointers and publishes the complete set; partial visibility or mixed old/new text and clips is impossible.
- Player URL signing resolves only the current evidence clip object.
- Linking a player account creates a matching player team membership.

## Deletion

Normal roster removal sets `active=false` and `deleted_at`, revokes membership/access, and does not claim erasure. Verified erasure marks `deletion_pending_at`, fences all affected video jobs/signing, and uses a restricted durable deletion manifest. The default shared-footage scope includes every stored video for that player's team and all video-dependent observations, judgments, revisions, publication items, clips, and reflections, including other players' affected evidence. Delete dependent rows in FK-safe order; remove empty publications. Preserve unrelated goals/accounts only after operator personal-data review. The manifest survives deletion of job target FKs until object absence and restore replay are verified; it contains IDs/object keys only, no content or signed URLs, and is never logged or user-visible. Task 22 owns its RLS and bounded retention. See the deadlines and operator confirmation requirements in `docs/10-security-privacy.md`.
