# 02 — Architecture

## Governing constraints

1. The product works with no ML and no GPU.
2. Video bytes do not pass through FastAPI.
3. Players never receive a full-match object.
4. Authorization is enforced in Postgres RLS and checked again in services.
5. One team and modest load favor a monorepo and a small number of processes.

## Live system

```text
Browser
  ├─ same-origin pages and JSON ──> Next.js on Vercel
  │                                  ├─ Supabase SSR session cookies
  │                                  └─ BFF forwards bearer JWT ──> FastAPI on Fly.io
  │                                                                  ├─ Postgres on Supabase
  │                                                                  └─ mints R2 object URLs
  └─ presigned PUT/GET ─────────────────────────────────────────────> private R2

Postgres processing_job ──> CPU worker on Fly.io ──> ffmpeg ──> private R2
```

The BFF handles only session-aware JSON. Large uploads and media downloads go directly between the browser and R2 through object-specific, short-lived presigned URLs.

## Authentication and request context

1. The user requests a Supabase magic link through Next.js.
2. The auth callback completes a PKCE flow and stores the session in Secure, HttpOnly, SameSite=Lax cookies.
3. The current framework-supported Next.js proxy/session-refresh boundary refreshes expired Auth cookies and verifies identity with Supabase SSR `getClaims()` before protected rendering.
4. A browser JSON request goes to the same-origin BFF. The BFF verifies claims again where required and may call `getSession()` only to retrieve the access token that must be forwarded; it never trusts the session's embedded user object for authorization.
5. FastAPI verifies signature, issuer, audience, algorithm, expiry, and subject from the project's JWKS.
6. FastAPI begins one database transaction and runs a transaction-local `app.user_id` setting with the verified subject UUID.
7. Queries execute through a dedicated API database role with `NOBYPASSRLS`.
8. The transaction ends, clearing the local context before the pooled connection is reused.

Do not authorize from editable `user_metadata`. Team roles live in database rows.

## Database exposure boundary

Product tables live in an `app` schema that is not enabled in Supabase Data API exposed schemas. FastAPI connects directly to Postgres with an explicit `app, pg_catalog` search path and a least-privilege runtime role. A separate `private` schema contains narrowly granted policy and Auth-sync helpers. No application helper relies on an unqualified object name.

RLS remains enabled and forced where designed even though the Data API cannot expose these tables. This protects against missed service filters and constrains direct runtime-role queries. Migration and administrative roles remain separate from the runtime role.

## Video path

### Upload

1. Browser sends filename, MIME type, exact size, and checksum metadata to the API.
2. API creates a `video` row and an R2 multipart upload.
3. API returns URLs for 32 MiB parts; the browser sends three parts concurrently.
4. Browser persists upload ID and completed ETags locally.
5. On interruption, the browser lists server-known parts and uploads only missing parts.
6. Closing the tab pauses the upload; reopening and reselecting the identical file resumes it.
7. API completes the multipart upload idempotently and enqueues transcode and thumbnail jobs.

### Coach playback

The worker creates `playback/{video_id}/coach-720p.mp4` with H.264 video, AAC audio or no audio, fast-start metadata, and roughly two-second keyframe spacing. R2 supports byte-range GET requests, allowing the browser to seek without downloading the full match.

Only coaches can request a signed URL to this object. The initial expiry target is 15 minutes, refreshed while the review screen is open.

### Player clips

Publishing creates one `review_publication` plus three to six ordered item rows, then enqueues one clip export per item. The worker writes `clips/{judgment_id}/{version}.mp4` and attaches the ready object to that item. The publication remains player-invisible while any item is pending or failed. After every current item succeeds, one database transaction switches each judgment's current clip and marks the complete set published. Player endpoints sign only these clip objects, never the coach playback object.

Use re-encoding at exact boundaries when stream-copy would expose excessive context or begin on the wrong keyframe. Clip correctness and privacy matter more than saving one second of CPU.

## Background jobs

Use one Postgres table and `FOR UPDATE SKIP LOCKED`. Required fields include `kind`, `status`, `available_at`, `attempts`, `max_attempts`, `locked_at`, `locked_by`, `heartbeat_at`, `progress`, `payload`, and a plain-language error.

Rules:

- Claim inside a short transaction.
- Jobs are idempotent by a deterministic key such as `transcode:{video_id}:v1`.
- Backoff changes `available_at`; never overload `created_at`.
- The worker heartbeats during ffmpeg work.
- A sweeper requeues expired leases only when attempts remain.
- Cancellation is cooperative between stages.
- Terminal failure is visible to the coach and never discards the original upload.

No Redis or external broker before measured volume exceeds this design.

## Offline computer vision

```text
selected video segment
  -> local frame preparation
  -> encrypted transfer to a manually started RunPod Secure Cloud pod
  -> SoccerMaster run
  -> immutable artifact JSON and Parquet
  -> pod destroyed
  -> local ingest
  -> coach assigns tracklets to players
  -> rules nominate observation rows
```

The GPU is never in an HTTP request path. The live product reads artifact files if they exist and behaves normally if they do not.

## Data tiers

| Tier | Data | Location |
|---|---|---|
| Raw media | Original upload, coach playback, thumbnails, isolated clips | Private R2 |
| Raw CV | Per-frame boxes, ball positions, trajectories | Parquet/JSON in private R2 |
| CV index | One row per run and tracklet | Postgres |
| Product meaning | Goal, observation, judgment, reflection | Postgres |

Never create a per-frame Postgres table.

## R2 layout and retention

```text
originals/{video_id}/source.{ext}                 delete after 90 days
playback/{video_id}/coach-720p.mp4               season + 1 year
thumbs/{video_id}/sprite-{n}.jpg                  season + 1 year
thumbs/{video_id}/index.json                      season + 1 year
clips/{judgment_id}/{version}.mp4                 season + 1 year
artifacts/{cv_run_id}/raw.json.gz                 research retention policy
artifacts/{cv_run_id}/tracks.parquet              research retention policy
```

All buckets remain private. CORS lists only the production and local app origins. Signed URLs are specific to one object and HTTP verb. Keys, tokens, and signed URLs never enter logs.

## Repository layout

```text
shoulder/
├── AGENTS.md
├── CLAUDE.md
├── STATUS.md
├── apps/web/
├── services/api/
├── services/worker/
├── db/migrations/
├── db/policies/
├── cv/prepare/
├── cv/runner/
├── cv/ingest/
├── cv/candidates/
├── cv/eval/
├── infra/
├── scripts/
├── tests/
└── docs/
```

SoccerMaster itself, model weights, raw footage, datasets, and generated CV frames stay outside the repository and are gitignored.

## Local development

- Node.js current supported LTS; pnpm
- Python 3.11 for web services; `uv`; ruff
- Supabase CLI-managed local Auth/Postgres, using the project-supported Postgres 16 image; do not run a second application Postgres
- MinIO through Docker Compose for the R2-compatible storage boundary
- ffmpeg/ffprobe pinned in the worker image
- Supabase CLI and local image versions verified from current docs when Task 2 begins; an incompatibility with the Postgres 16 target requires an ADR

The GPU environment remains separate: Python 3.10.16, CUDA 12.1, PyTorch 2.4.1, and the versions required by the current SoccerMaster instructions.

## Performance budgets

| Operation | Target |
|---|---|
| JSON API p95 | < 300 ms excluding cold start |
| Coach playback first frame | < 2.5 s on normal broadband |
| Random coach seek | < 1.5 s p75 |
| Player clip first frame on 4G | < 2 s |
| Player page LCP | <= 2.5 s p75 |
| Player page INP | <= 200 ms p75 |
| Player page CLS | <= 0.1 p75 |
| Timeline ready | < 500 ms after metadata |
| Upload recovery | no completed part repeats |
| Clip ready after publish | < 90 s for six clips |

Real-time or live processing is explicitly not a goal.
