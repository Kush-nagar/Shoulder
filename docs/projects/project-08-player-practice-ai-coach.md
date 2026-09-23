# Block 08P — Player practice, AI coach, and demo deploy

Outside the canonical task graph. Authorised by [ADR 0021](../decisions/0021-player-practice-and-ai-coach.md).
Branch: `block-08p-player-practice` from `main` after the Google OAuth PR merges.

## Goal

A player signs in on a phone, uploads a practice clip, sees their pose overlay,
gets AI drill suggestions tied to their coach's `development_goal`, and installs
the app to the home screen. Deployed as a public demo with synthetic players.

## Frozen contracts (coordinator owns; workers must not redefine)

### Schema — migration `0014_player_practice`

```
app.practice_video
  id uuid pk, player_id uuid fk app.player (indexed), created_by_user_id uuid not null,
  object_key text not null unique, content_type text check in ('video/mp4','video/quicktime','video/webm'),
  size_bytes bigint check (size_bytes between 1 and 524288000),     -- 500 MB
  duration_ms integer null check (duration_ms between 1 and 600000), -- 10 min
  status text check in ('uploading','ready','deleted'),
  title text null check (char_length(title) <= 80),
  created_at timestamptz, upload_completed_at timestamptz null,
  expires_at timestamptz null   -- upload_completed_at + 90 days

app.ai_coach_feedback
  id uuid pk, practice_video_id uuid fk (indexed), player_id uuid fk (indexed),
  development_goal_id uuid null fk (indexed),
  features jsonb not null,   -- aggregate only; schema below; no landmarks
  model text not null, body text not null check (char_length(body) <= 1200),
  drills jsonb not null,     -- [{title, why, how}] max 3
  created_at timestamptz
```

RLS: the player whose `player.user_id = auth.uid()` may select/insert/delete their own rows;
nobody else, coaches included. Isolation tests: player A cannot read, sign, or delete
player B's practice video or feedback, at DB and API layers.

### Features JSON (browser → API), max 4 KB

```json
{"frames_analyzed": 900, "fps": 30, "duration_ms": 30000,
 "knee_flexion_deg": {"p10": 12, "p50": 34, "p90": 61},
 "hip_flexion_deg": {...}, "trunk_lean_deg": {...},
 "head_turns": 7, "head_turns_per_min": 14.0,
 "stance_width_ratio": {"p50": 1.2}, "visibility_mean": 0.82}
```

### API (FastAPI; TS types generated from OpenAPI, never hand-written)

| Method | Path | Notes |
|---|---|---|
| POST | `/player/practice-videos` | start upload; returns id + single presigned PUT (≤ 500 MB, 15 min) |
| POST | `/player/practice-videos/{id}/complete` | HEAD-verifies object, sets `ready`, `expires_at` |
| GET | `/player/practice-videos` | own list |
| GET | `/player/practice-videos/{id}` | detail + short-lived signed GET |
| DELETE | `/player/practice-videos/{id}` | deletes object + rows |
| POST | `/player/practice-videos/{id}/ai-feedback` | body = features JSON; rate limit 10/day/player; calls OpenRouter; filters; stores |
| GET | `/player/practice-videos/{id}/ai-feedback` | own feedback list |

Reuse `services/api/storage.py` signing and the `services/api/video.py` patterns; do not fork them.
Retention: extend `services/worker/retention.py` to purge expired practice videos.

### LLM call

- `OPENROUTER_API_KEY`, `AI_COACH_MODEL` (default `deepseek/deepseek-chat`) env; server-side only.
- System prompt: youth-soccer training assistant; input = features + goal title; output strict JSON
  `{body, drills[≤3]}`; no scores, ratings, percentages, comparisons, medical advice; encouraging,
  concrete, age 13–18.
- Output filter: JSON schema validation, banned words from `AGENTS.md` player copy,
  reject `%` and "/10"-style ratings; on failure return 502 and store nothing.
- Tests mock HTTP; no live model call in CI.

## Workstreams (parallel after W0)

| ID | Owner files | Deliverable | Depends |
|---|---|---|---|
| W0 | coordinator | ADR, this file, OAuth PR merged, branch cut | — |
| W1 DB+API | `migrations/versions/0014_*`, `services/api/practice_*.py`, `tests/**/test_practice_*` | schema, RLS, routes, retention, isolation tests, OpenAPI regen | W0 |
| W2 AI | `services/api/ai_coach.py`, `apps/web/app/player/practice/pose/*` | OpenRouter client + filter; browser MediaPipe worker producing features JSON + canvas overlay | W0 (API route wiring merges after W1) |
| W3 Frontend | `apps/web/app/player/**` (except `pose/`), `apps/web/app/api/player/practice/**`, `apps/web/public/manifest.webmanifest`, `apps/web/app/manifest.ts` | practice list/upload/detail pages, AI feedback card, player nav, PWA manifest + icons, mobile polish | W0 (types after W1) |
| W4 Demo | `scripts/seed-demo.ps1`, deploy docs | synthetic team/players/goals/published clips; Vercel + Fly config | W1 |
| W5 QA | `tests/practice.spec.mjs` | Playwright player flow + Chrome walkthrough, console clean | W1–W3 |

## Mobile

1. PWA now: `app/manifest.ts`, icons, `display: standalone`, `<input type="file" accept="video/*" capture>`
   for camera capture. No service-worker caching of video.
2. App stores later: Capacitor wrapper around the deployed URL. Not in this block.

## Done

- Player flow works in Chrome desktop + mobile emulation with zero console errors.
- Isolation tests pass; `scripts/check.ps1` and `scripts/check-db.ps1` green.
- AI feedback: mocked tests pass; one live manual call on the dev project recorded.
- Demo deployed with synthetic data only; URL recorded in `STATUS.md`.

## Not in this block

Coach-side changes, Capacitor, ball detection/YOLO (AGPL), HLS, sharing practice video with coach.
