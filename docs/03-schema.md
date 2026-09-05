# 03 — Database contract

Postgres 16. Product tables live in a non-exposed `app` schema; narrowly scoped helpers live in `private`. Every change is an Alembic migration. Every foreign key is indexed. All timestamps are `timestamptz`. All media offsets are non-negative integer milliseconds relative to the original uploaded file and use the `*_ms` suffix.

This document is a schema contract, not a migration script.

## Identity and authorization context

`user_account.id` is the Supabase Auth subject UUID and references `auth.users(id)`. Do not generate a second application identity.

FastAPI validates the bearer JWT, starts a transaction, and sets `app.user_id` transaction-locally. Policies use a stable helper in the `private` schema that returns `current_setting('app.user_id', true)::uuid`. The API connects as a dedicated `NOBYPASSRLS` role with an explicit search path. Test that the role does not own protected tables, cannot disable RLS, and has no Data API-facing grants.

Do not use `user_metadata` for authorization. Team roles come from `team_membership`.

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
| `status` | `uploading`, `uploaded`, `processing`, `ready`, `failed`, `deleted` |
| `uploaded_by`, `created_at`, `ready_at`, `deleted_at` | audit and lifecycle |

Indexes: `game_id`, `status`. The state machine rejects backward transitions except explicit retry from `failed` to `processing`.

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

Indexes: `(video_id, player_id, t_start_ms)` and `(video_id, source)`. Observation rows are append-only. A rejected candidate remains for later precision measurement.

### `judgment`

| Column | Rules |
|---|---|
| `id` | uuid PK |
| `observation_id` | non-null FK observation |
| `goal_id` | non-null FK development goal |
| `author_user_id` | non-null FK user account; server-derived only |
| `verdict` | `applied`, `opportunity`, `not_relevant` |
| `comment_text` | nullable in draft; 1–400 characters when published |
| `clip_start_ms`, `clip_end_ms` | required for exporting; end greater than start |
| `publication_status` | `draft`, `exporting`, `published`, `withdrawn`, `failed` |
| `current_clip_id` | nullable unique FK to the current ready `evidence_clip`; server-managed |
| `published_at`, `updated_at`, `created_at` | timestamps |

Unique `(observation_id, goal_id)`. Check that `not_relevant` can never have `publication_status='published'`. Index `(goal_id, published_at desc)`.

Publication is a state machine. The API sets all judgments in one requested set to `exporting`; each successful export creates an evidence clip and attaches it to the corresponding publication item. Only after every item in the three-to-six-judgment set is ready does one transaction switch every `current_clip_id`, set the complete set to `published`, and publish the batch. A player policy checks both judgment and publication state, not a client-controlled Boolean. The migration adds the `current_clip_id` foreign key after `evidence_clip` exists.

### `evidence_clip`

`id`, `judgment_id`, `version`, `storage_key`, `duration_ms`, `size_bytes`, `sha256`, `status`, `created_at`, `ready_at`, `deleted_at`.

- Unique `(judgment_id, version)`.
- At most one current version, selected only by `judgment.current_clip_id` after the related publication succeeds.
- Storage key is returned only through an authorized signing service; never directly in player DTOs.

### `review_publication`

| Column | Rules |
|---|---|
| `id` | uuid PK |
| `game_id`, `player_id`, `goal_id` | non-null FKs; the service verifies one consistent review context |
| `requested_by` | non-null FK `user_account`; server-derived |
| `idempotency_key` | non-null unique |
| `status` | `exporting`, `published`, `failed`, `withdrawn` |
| `requested_count` | smallint; check 3 through 6 |
| `created_at`, `updated_at`, `published_at` | timestamps |

Index `(player_id, published_at desc)` and `(game_id, player_id)`. A failed item makes the publication `failed` but leaves every draft and successfully exported private object recoverable for retry. Repeating the same idempotency key returns this row rather than creating another batch.

### `review_publication_item`

`publication_id`, `judgment_id`, `ordinal`, `requested_clip_version`, nullable `evidence_clip_id`, `created_at`, `updated_at`.

- Primary key `(publication_id, judgment_id)`.
- Unique `(publication_id, ordinal)` with ordinal bounded from 1 through 6.
- `evidence_clip_id` is set only after checksum and boundary validation succeed.
- The evidence clip must belong to the same judgment and requested version; enforce transactionally and test it.
- Items are immutable except for attaching or replacing the requested clip during an explicit retry.
- A judgment may belong to only one nonterminal (`exporting`) publication at a time. Enforce this with a transaction-level advisory lock or equivalent database-backed serialization keyed by judgment ID; do not rely on an in-process mutex.

### `player_reflection`

`id`, `judgment_id`, `player_id`, `text`, `created_at`, `updated_at`; unique `judgment_id`; 1–1,000 characters. The service verifies that the authenticated player's linked `player.id` matches the judgment's goal owner. Removing a reflection deletes this row and records only the allowed operational event.

## Deferred CV tables

### `cv_run`

`id`, `segment_id`, `pipeline`, `pipeline_version`, `artifact_key`, `artifact_sha256`, `gpu_seconds`, `notes`, `ingested_at`. Unique artifact checksum per pipeline version.

### `player_track`

`id`, `cv_run_id`, `track_ref`, `t_start_ms`, `t_end_ms`, `role`, `team_side`, advisory jersey fields, nullable coach-assigned `player_id`; unique `(cv_run_id, track_ref)`. No appearance embedding columns.

Per-frame trajectories stay in Parquet in R2.

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
| `observation` | coached-team CRUD/append | no access |
| `judgment` | coached-team author CRUD | own `published` rows read-only |
| `review_publication`, `review_publication_item` | coached-team read/create/update through service state machine | own published rows read-only |
| `evidence_clip` | coached teams | own ready clip for a published judgment |
| `player_reflection` | coached teams read | own insert/read/update/delete |
| `cv_run`, `player_track` | coached teams | no access |
| `product_event` | service-only writes; limited operator reads | no direct access |

Use separate SELECT, INSERT, UPDATE, and DELETE policies when their predicates differ. UPDATE requires both `USING` and `WITH CHECK`. Enable and force RLS on protected application tables, and test through the same database role used in production.

## Invariants enforced in service and test

Some cross-table rules cannot be a simple check constraint and must be transactionally enforced:

- Judgment goal and observation belong to the same player.
- Observation player belongs to the video's game team.
- Clip boundaries remain inside video duration.
- No more than six judgments per player/game become published.
- A publication contains exactly 3–6 distinct judgments from the same player, game, and active goal.
- Concurrent requests cannot place the same judgment in two nonterminal publications.
- A judgment becomes published only when every item in its explicit publication is attached to a ready evidence clip.
- One transaction switches all current clip pointers and publishes the complete set; partial visibility is impossible.
- Player URL signing resolves only the current evidence clip object.
- Linking a player account creates a matching player team membership.

## Deletion

Normal roster removal sets `player.deleted_at` and blocks access. A verified hard-delete job removes dependent product rows and R2 objects, then deletes or anonymizes operational events. The deletion test begins with raw, playback, thumbnail, clip, and CV artifact objects and proves none remain.
