# 04 — API contract

FastAPI routes live under `/v1`. Browser requests use the same-origin Next.js BFF, which verifies claims and forwards the Supabase access token to FastAPI. Retrieving a session solely to access its token does not authorize the embedded user object. FastAPI independently validates the JWT and relies on Postgres RLS for final row authorization.

The browser never receives a Supabase secret/service key. The API never accepts `author_user_id`, `team_id` ownership, storage keys, or publication state from an untrusted request when those values can be derived server-side.

## Auth surfaces

These are Next.js routes because Next.js owns cookies and the PKCE callback.

| Method | Browser route | Purpose |
|---|---|---|
| POST | `/auth/magic-link` | Request sign-in email; rate-limited; generic response |
| GET | `/auth/callback` | Exchange verified code, set secure session; role routing is added in Task 4 |
| POST | `/auth/sign-out` | Revoke local session and clear cookies |

Task 3 proves verified session identity through auth-boundary integration tests, without a role-aware product endpoint or placeholder role. It can render a neutral signed-in state with no product access. Task 4 completes the following FastAPI endpoint and role routing after its protected identity/membership schema exists:

Task 3's narrow `GET /v1/auth/identity` returns only `{"user_id": "<verified UUID>"}`;
the browser counterpart is `GET /api/auth/identity`. Both verify the token and
live Auth session, return non-cacheable responses, and grant no team permissions.
See ADR 0014. This identity proof does not implement or substitute for `/v1/me`.

| Method | Route | Auth | Response |
|---|---|---|---|
| GET | `/v1/me` | verified identity | User, database-derived allowed roles, linked player, team IDs; unlinked account has empty roles/teams and no product access |

Do not trust a cookie's user object without validating claims. Do not put team roles in editable metadata.

Task 4 includes the restricted operator-only initial coach/team bootstrap, matching membership and account linkage, and revoked-membership acceptance tests. Auth signup alone never grants a coach role.

## Teams and roster

| Method | Route | Auth | Request / behavior |
|---|---|---|---|
| POST | `/v1/teams` | authorized operator bootstrap | Create the single initial team and designated coach membership atomically only when none exists; no public role elevation |
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
| POST | `/v1/judgments/{judgment_id}/withdraw` | team coach | Clears current visibility, cancels pending replacement for player/game, and blocks future signing |
| GET | `/v1/judgments/{judgment_id}/revisions` | team coach | Immutable revision history; player access denied |
| GET | `/v1/review-publications/{publication_id}` | team coach | Ordered pinned revisions, aggregate status, retry/cancel state |
| POST | `/v1/review-publications/{publication_id}/cancel` | team coach | Cancels pending export/retry without changing the previous published set |

Publish rules:

- All judgments belong to the same player, game, and active goal. Closed goals permit withdrawal but cannot publish until explicitly reactivated within the one-active-goal rule.
- Count is 3–6.
- `not_relevant` is rejected.
- Every item has a non-empty coach comment and valid clip boundaries.
- Each ordered item carries `judgment_id` and the expected `version`. The server resolves and pins that immutable revision. A stale version returns 409. A replacement also names `replaces_publication_id`, which must equal the current set for this player/game and goal; first publication requires no current set. One current set per player/game enforces the six-clip cap across requests.
- Serialize both the player/game context and overlapping judgments in Postgres. Only one exporting request per context is allowed. While a judgment is reserved, content edits return 409. A changed set requires cancelling the pending publication and a new request; retry preserves the exact pinned versions and order.
- Request requires an idempotency key; replay returns the same publication.
- Retrying a failed export reacquires reservations and verifies that every pinned version is still latest and no intervening withdrawal, expiry, or predecessor change occurred. Otherwise return 409 and require a deliberate new publication; retry never revives an invalidated request.
- Response is `202` with the `review_publication`, ordered items, and sanitized aggregate state.
- The requested publication stays `exporting` and its new snapshots remain player-invisible until every pinned clip exists. On replacement, the old publication remains visible with its old text/verdicts/clips through editing, export, failure, and cancellation. One transaction supersedes the old set, switches all current revision/clip pointers, and removes omitted items. Revalidate current membership, active goal, predecessor, expiry, and deletion/withdrawal state before finalization.
- Email sends once after the complete set is published, not once per clip.

Judgment creation writes revision 1. PATCH requires `If-Match` for the latest positive integer `version`, returns the new version/ETag, and appends a full immutable revision on every content change. Missing precondition returns 428; stale version returns 409 with the latest coach-authorized snapshot for conflict recovery. No-op or idempotent replay does not increment. Only the original author with current team authorization may edit. Observation, goal, author, version, and publication pointers are server-managed. Coach DTOs clearly distinguish latest draft from currently published revision.

Any published-content change, even only a sentence, requires explicit full-set republication. Worker exports consume the pinned revision; changed revisions get new isolated clip objects. Withdrawal immediately prevents new reads/signing, even if this leaves fewer than three clips, and cancels pending replacement so a delayed job cannot republish it. Already issued player URLs expire within five minutes; obsolete objects are removed within 24 hours. Replaying a request key with different content returns 409.

## Player-facing routes

| Method | Route | Auth | Behavior |
|---|---|---|---|
| GET | `/v1/me/goals` | player | Own goals only |
| GET | `/v1/me/goals/{goal_id}/evidence` | player | Own published judgments grouped by game; no rejected rows |
| POST | `/v1/me/judgments/{judgment_id}/clip-url` | player | Expected published revision ID; signs only its current ready isolated clip, maximum five-minute URL |
| GET | `/v1/me/reflections` | player | Own reflections, including those whose evidence was withdrawn; no withdrawn coach text/media |
| PUT | `/v1/me/judgments/{judgment_id}/reflection` | player author | Explicit create or edit intent, text, expected row ID/ETag, request creation timestamp within seven days, and idempotency key; one per judgment |
| DELETE | `/v1/me/judgments/{judgment_id}/reflection` | player author | Permanently delete own reflection and invalidate old saves; idempotent, including after evidence withdrawal |

The evidence DTO contains the coach's display name, player-safe verdict copy, comment, game label, clip duration, judgment ID, and published revision ID. Text/verdict/bounds come only from `current_revision_id`, never the latest draft. It does not contain `video_id`, original storage keys, coach playback URLs, CV confidence, CV features, team totals, draft history, or other players. If clip signing's expected published revision no longer matches, return 409 and refresh the entire evidence set; never pair old text with a replacement clip.

Reflection creation requires visible evidence; editing/deleting an existing own row remains allowed after withdrawal while account access remains valid. Coach text and URLs stay hidden. Identity fields are server-derived and immutable. Capture the current published version at save time, or retain its last marker if no evidence is current; indicate an older reflection after republication without revealing old coach revisions. Edits retain no text history. DELETE removes live/cached/queued text and records only bounded content-free replay metadata. Serialize save/delete; an old save retry cannot recreate a deleted row or overwrite a newer edit. A deliberate new create uses a new key and visible evidence. The API reports 204 only after active deletion; backup limits and restore replay follow `docs/10-security-privacy.md`.

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

The operator player-data deletion challenge enumerates the conservative shared-footage impact: all stored team videos and all dependent evidence, including other players' affected clips. Start by fencing access/exports; preserve a restricted manifest until objects, FK-ordered rows, and restore suppression reconcile. Unrelated accounts/goals require operator personal-data review before retention. A roster archive is access removal, not erasure. See ADR 0009 in `docs/decisions/0009-retention-and-shared-footage-deletion.md`. Ordinary author reflection deletion uses its dedicated route and does not require this operator challenge.

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
