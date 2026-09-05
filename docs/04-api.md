# 04 — API contract

FastAPI routes live under `/v1`. Browser requests use the same-origin Next.js BFF, which verifies claims and forwards the Supabase access token to FastAPI. Retrieving a session solely to access its token does not authorize the embedded user object. FastAPI independently validates the JWT and relies on Postgres RLS for final row authorization.

The browser never receives a Supabase secret/service key. The API never accepts `author_user_id`, `team_id` ownership, storage keys, or publication state from an untrusted request when those values can be derived server-side.

## Auth surfaces

These are Next.js routes because Next.js owns cookies and the PKCE callback.

| Method | Browser route | Purpose |
|---|---|---|
| POST | `/auth/magic-link` | Request sign-in email; rate-limited; generic response |
| GET | `/auth/callback` | Exchange verified code, set secure session, redirect by role |
| POST | `/auth/sign-out` | Revoke local session and clear cookies |

FastAPI exposes:

| Method | Route | Auth | Response |
|---|---|---|---|
| GET | `/v1/me` | coach/player | User, allowed roles, linked player, team IDs |

Do not trust a cookie's user object without validating claims. Do not put team roles in editable metadata.

## Teams and roster

| Method | Route | Auth | Request / behavior |
|---|---|---|---|
| POST | `/v1/teams` | coach | Create the initial team |
| GET | `/v1/teams` | both | Only memberships visible through RLS |
| GET | `/v1/teams/{team_id}/players` | coach | Active roster only by default |
| POST | `/v1/teams/{team_id}/players` | coach | Name, optional number and position |
| POST | `/v1/teams/{team_id}/players/bulk` | coach | Up to 40 parsed rows; all-or-nothing validation |
| PATCH | `/v1/players/{player_id}` | coach | Allowed profile fields only |
| POST | `/v1/players/{player_id}/invite` | coach | Email; creates or links account safely |
| POST | `/v1/players/{player_id}/archive` | coach | Soft removal from active roster |

Bulk creation returns per-row validation details before writing. Never create the valid subset while silently dropping invalid rows.

## Games and upload

| Method | Route | Auth | Request / response |
|---|---|---|---|
| POST | `/v1/games` | coach | Team, opponent, date, match kind |
| GET | `/v1/games/{game_id}` | coach | Game, video state, per-player review state |
| GET | `/v1/teams/{team_id}/games` | coach | Cursor list; optional pending filter |
| POST | `/v1/games/{game_id}/videos/uploads` | coach | Filename, size, MIME, checksum metadata -> upload session |
| POST | `/v1/videos/{video_id}/upload-parts/sign` | coach | Part numbers -> short-lived presigned PUT URLs |
| GET | `/v1/videos/{video_id}/upload-state` | coach | Server-confirmed completed part numbers and ETags |
| POST | `/v1/videos/{video_id}/upload-complete` | coach | Completed part list; idempotent -> video/job state |
| POST | `/v1/videos/{video_id}/upload-abort` | coach | Abort incomplete upload |
| GET | `/v1/videos/{video_id}` | coach | Metadata and processing state; no storage keys |
| POST | `/v1/videos/{video_id}/playback-url` | coach | 15-minute signed URL to coach playback object |
| GET | `/v1/videos/{video_id}/timeline` | coach | Signed sprite URLs and timestamp index |
| POST | `/v1/videos/{video_id}/segments` | coach | Create an offline-CV segment |

Validate filename extension and probed media type; do not trust the request's MIME type. Part URLs authorize only one exact object, part number, upload ID, HTTP method, and short expiry.

The client may cache resume state, but `upload-state` is authoritative. Closing a tab pauses an unfinished upload.

## Goals

| Method | Route | Auth | Behavior |
|---|---|---|---|
| POST | `/v1/players/{player_id}/goals` | coach | Creates active goal or requires explicit closure of current goal |
| GET | `/v1/players/{player_id}/goals` | both | Coach: team player; player: self only |
| PATCH | `/v1/goals/{goal_id}` | coach | Title, description, or valid status transition |

An `ontology_key` is optional and coach-invisible unless useful. It never restricts free-text coaching goals.

## Observations and judgments

| Method | Route | Auth | Behavior |
|---|---|---|---|
| GET | `/v1/videos/{video_id}/observations` | coach | Filters by player/source; includes drafts and CV candidates |
| POST | `/v1/videos/{video_id}/observations` | coach | Creates a manual time range for a roster player |
| POST | `/v1/observations/{observation_id}/judgments` | coach | Goal, verdict, comment, clip bounds; author from session |
| PATCH | `/v1/judgments/{judgment_id}` | coach author/team | Updates allowed draft fields with optimistic version |
| POST | `/v1/reviews/{game_id}/{player_id}/publish` | coach | Three to six ordered judgment IDs -> `review_publication` export batch |
| POST | `/v1/judgments/{judgment_id}/withdraw` | coach | Removes player visibility and expires future signing |

Publish rules:

- All judgments belong to the same player, game, and active goal.
- Count is 3–6.
- `not_relevant` is rejected.
- Every item has a non-empty coach comment and valid clip boundaries.
- No requested judgment is already reserved by another nonterminal publication; the service serializes this check in Postgres.
- Request requires an idempotency key; replay returns the same publication.
- Response is `202` with the `review_publication`, ordered items, and sanitized aggregate state.
- The complete requested set stays `exporting` and player-invisible until every current clip exists; one database transaction then publishes the set.
- Email sends once after the complete set is published, not once per clip.

Draft updates carry a version or `If-Match` value. A stale write returns `409` with enough information to recover without discarding local edits.

## Player-facing routes

| Method | Route | Auth | Behavior |
|---|---|---|---|
| GET | `/v1/me/goals` | player | Own goals only |
| GET | `/v1/me/goals/{goal_id}/evidence` | player | Own published judgments grouped by game; no rejected rows |
| POST | `/v1/me/judgments/{judgment_id}/clip-url` | player | Signs only the current ready `evidence_clip` object |
| PUT | `/v1/me/judgments/{judgment_id}/reflection` | player | Create or replace optional own reflection; one per judgment |
| DELETE | `/v1/me/judgments/{judgment_id}/reflection` | player | Remove own reflection idempotently |

The evidence DTO contains the coach's display name, player-safe verdict copy, comment, game label, clip duration, and judgment ID. It does not contain `video_id`, original storage keys, coach playback URLs, CV confidence, CV features, team totals, or other players.

## Coach development record

| Method | Route | Auth | Behavior |
|---|---|---|---|
| GET | `/v1/players/{player_id}/development` | coach | Goal and raw evidence dots grouped by game |
| GET | `/v1/players/{player_id}/reflections` | coach | Cursor list of that player's reflections |

The development route never returns a percentage, average, score, predicted trend, comparison, or multi-player aggregate.

## Jobs and deletion

| Method | Route | Auth | Behavior |
|---|---|---|---|
| GET | `/v1/jobs/{job_id}` | coach | Sanitized status, progress, retryability, action |
| POST | `/v1/jobs/{job_id}/retry` | coach | Valid only for retryable terminal failure |
| POST | `/v1/jobs/{job_id}/cancel` | coach | Cooperative cancellation |
| POST | `/v1/players/{player_id}/data-export` | authorized operator | Starts verified export workflow |
| DELETE | `/v1/players/{player_id}/data` | authorized operator | Confirmed hard-delete workflow, async |

Destructive routes require recent authentication and an explicit confirmation challenge. Do not expose them to ordinary player UI without an approved request process.

## Deferred CV ingest

| Method | Route | Auth | Behavior |
|---|---|---|---|
| POST | `/v1/cv-runs` | coach/operator | Registers immutable artifact metadata; no inference |
| GET | `/v1/cv-runs/{run_id}/tracks` | coach | Tracklet index and thumbnails |
| POST | `/v1/cv-runs/{run_id}/assignments` | coach | Coach-selected track-to-player mapping |
| POST | `/v1/cv-runs/{run_id}/generate-candidates` | coach/operator | Enqueues deterministic rule processing |

There is no `/analyze`, `/score`, `/coach`, or generated-feedback endpoint.

## Response conventions

- JSON uses `snake_case` at the API boundary unless a single project-wide transform is deliberately chosen and generated types preserve it.
- Creates return `201`; asynchronous starts `202`; successful idempotent deletes `204`.
- Use cursor pagination for lists that can exceed 100 rows.
- Return `404` for RLS-hidden resources to avoid confirming their existence.
- Return `409` for stale versions or invalid state transitions.
- Return `422` for field validation.
- All asynchronous mutations accept an `Idempotency-Key` header.

Error body follows RFC 9457 problem details:

```json
{
  "type": "https://shoulder.local/problems/invalid-clip-boundaries",
  "title": "Clip boundaries are invalid",
  "status": 422,
  "detail": "The clip must end after it starts and remain inside the video.",
  "instance": "/v1/judgments/…"
}
```

Do not include stack traces, SQL, tokens, signed URLs, player names, coach comments, storage keys, or raw provider errors.

## Generated client contract

FastAPI's OpenAPI document is the only API type source. CI generates TypeScript types and fails if generated output differs. Frontend code does not hand-write parallel request or response interfaces.
