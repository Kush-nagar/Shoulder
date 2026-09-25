# Block 09B — Session tracking, team leaderboards, coach tools, mobile app

Outside the canonical task graph. Owner-requested (borrowing from Ballers Club).
Authorised by [ADR 0023](../decisions/0023-session-tracking-and-team-leaderboards.md)
and [ADR 0021](../decisions/0021-player-practice-and-ai-coach.md).
Integration branch: `ballers-features` from `main`.

## Goal

A player records a training session or match with their phone, sees distance,
speed, sprints, a heatmap and half-time splits, tracks progress over time, and
can opt into a team leaderboard. Their team coach assigns drills and training
plans and sees the team's tracking. The app ships to phones as a Capacitor
wrapper. A coach marketplace is designed, not built.

## Workstreams

| ID | Owner area | Depends | Parallel with |
|---|---|---|---|
| W1 Tracking | migration 0016, `services/api/tracking_*.py`, `apps/web/app/player/sessions/**`, `apps/web/app/player/sessions/tracking/*` | W0 | W3, W4 |
| W2 Leaderboard | migration 0017, `services/api/leaderboard_*.py`, `apps/web/app/player/team/**` | W1 merged | W3, W4 |
| W3 Coach tools | fix failing coach suites; migration 0018, `services/api/plan_*.py`, `apps/web/app/coach/**`, plan card on player home | W0 | W1, W4 |
| W4 Mobile | `apps/mobile/**` (Capacitor), `docs/mobile.md` | W0 | all |
| W5 Marketplace design | `docs/design/coach-marketplace.md` only | W0 | all |

Migration numbers are fixed: 0016 = W1, 0017 = W2, 0018 = W3. W3 writes 0018
with `down_revision = "0016_training_sessions"` only after W1 merges; until then
it develops against its own branch and is rebased by the coordinator.

## Frozen contracts

### 0016_training_sessions (W1)

```
app.training_session
  id uuid pk, player_id uuid fk app.player on delete cascade (indexed),
  kind text check in ('training','match'),
  started_at timestamptz not null, ended_at timestamptz not null check (ended_at > started_at),
  duration_s integer check (duration_s between 60 and 14400),
  distance_m integer check (distance_m between 0 and 30000),
  top_speed_cms integer check (top_speed_cms between 0 and 1300),   -- cm/s, ≤ 46.8 km/h
  sprint_count integer check (sprint_count between 0 and 500),       -- > 25 km/h for ≥ 1 s
  half_split_s integer null check (half_split_s > 0),                 -- seconds from start
  heatmap smallint[] not null check (array_length(heatmap,1) = 96),   -- 12×8, normalised 0..1000
  heatmap_second_half smallint[] null check (array_length(heatmap_second_half,1) = 96),
  gps_quality text check in ('good','fair','poor'),
  note text null check (char_length(note) <= 280),
  created_at timestamptz default now()
```
RLS: player self select/insert/delete; the player's team coach select. Retention:
purge after 365 days (sweep in `services/worker/retention.py`); cascades on erasure.

API: `POST /v1/player/sessions` (body = the columns above minus id/player_id/created_at;
server re-validates bounds and rejects any lat/long-shaped field), `GET /v1/player/sessions`,
`GET /v1/player/sessions/{id}`, `DELETE /v1/player/sessions/{id}`,
`GET /v1/player/sessions/summary?weeks=12` (per-week totals + personal records),
`GET /v1/players/{player_id}/sessions` (team coach).

Browser: `sessions/tracking/track.ts` exports `startTracking(onUpdate)` →
`{ stop(): SessionSummary, markHalfTime() }`. Uses `navigator.geolocation.watchPosition`
(high accuracy) + Screen Wake Lock; drops fixes with accuracy > 25 m; speed from
successive fixes with a 3-sample median; heatmap by projecting points onto the
track's principal axes (PCA) into a 12×8 grid. Raw points stay in memory only.
Pure math in `sessions/tracking/metrics.ts` with a Node test.

### 0017_team_leaderboard (W2)

```
app.leaderboard_member
  player_id uuid pk fk app.player on delete cascade,
  nickname text not null check (nickname ~ '^[A-Za-z0-9 ]{2,20}$'),
  joined_at timestamptz default now()
```
RLS: player self insert/update/delete/select; same-team members read through a
SECURITY DEFINER function `private.team_leaderboard(p_team_id, p_metric, p_since)`
returning `(nickname, value, is_me)` for opted-in players of that team only.
API: `PUT/DELETE /v1/player/leaderboard-membership`, `GET /v1/teams/{team_id}/leaderboard?metric=distance|sprints|top_speed|sessions&period=week|season`.

### 0018_training_plans (W3)

```
app.training_plan
  id uuid pk, team_id uuid fk (indexed), player_id uuid null fk (indexed),  -- null = whole team
  created_by uuid not null (coach, from session), title text check (1..80),
  week_of date not null, items jsonb not null  -- [{drill_slug, note ≤ 200}] 1..8
  created_at, updated_at
```
RLS: team coach all; player select where player_id = self or (player_id is null and member of team).
API: `GET/POST /v1/teams/{team_id}/plans`, `PATCH/DELETE /v1/plans/{id}`, `GET /v1/player/plans`.
Drill slugs come from `apps/web/content/drills.ts`; the API validates slug shape only.

## Web surfaces

- Player: `/player/sessions` (list + weekly chart), `/player/sessions/new` (live
  tracker: big timer, distance, "Half-time", "Finish"), `/player/sessions/[id]`
  (stats, heatmap, half splits), `/player/team` (opt-in with nickname, board),
  Home cards: "This week" totals and "From your coach" plan. Nav adds **Sessions**.
- Coach: dashboard at `/coach` (team week at a glance), plans editor, player
  tracking view. Coach pages adopt the ADR 0022 design tokens.

## Mobile (W4)

Capacitor 7 app in `apps/mobile` loading the production URL (`server.url`) with
native plugins: Geolocation (foreground), Camera, Keep Awake, Status Bar, Splash.
Android project generated and buildable on Windows (debug APK); iOS project
generated for a Mac/Xcode build. Document store-review risk (Apple 4.2) and the
features that justify native (tracking, camera capture).

## Verification

Per workstream: ruff, mypy on touched files, targeted unit tests, web typecheck,
Biome, Node tests, `pnpm build`. Agents must NOT run `scripts/check-db.ps1` or
migrate/downgrade the shared local database; the coordinator runs DB suites
serially after integration. Coordinator: `check-db.ps1`, walkthrough extended
to sessions/team/plans, independent security review (RLS, leaderboard exposure,
location privacy) before merge.

## Running an agent on a workstream

Claude Code: the coordinator spawns one agent per workstream with this file.
Fallback when Claude usage is exhausted (OpenCode, configured in
`~/.config/opencode/opencode.jsonc`):

```
opencode run -m openrouter/deepseek/deepseek-v3.2 "Read AGENTS.md, CLAUDE.md and docs/projects/project-09-ballers-features.md. Implement workstream W<n> exactly as frozen. Run its verification. Commit on branch ballers-w<n>; do not push."
```
