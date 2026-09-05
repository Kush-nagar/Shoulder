# Shoulder repository instructions

Read this file, `STATUS.md`, `docs/01-product.md`, and the assigned task in `docs/06-tasks.md` before changing anything. Read only the additional documents named by that task.

## Product contract

Shoulder lets a coach publish three to six short, coach-authored clips for one player's active development goal. The player watches their own clips and may reflect. The users include minors.

The system may later retrieve candidate moments with computer vision. It never evaluates a child's ability, produces rankings, or authors player-facing text.

## Rules that override every task

1. **A human coach authors every judgment.** `judgment.author_user_id` is non-null and comes from the authenticated session. No model-generated text reaches a player.
2. **No scores or comparisons.** Do not create ratings, percentages, ranks, leaderboards, team averages, trend scores, or cross-player endpoints.
3. **RLS is mandatory.** Every table containing team, player, video, judgment, reflection, or event data ships with row-level-security policies and isolation tests.
4. **Players never receive full-match access.** Coach playback uses the coach-only playback object. Published player evidence uses a separate exported clip object.
5. **No ML before the Phase D gate.** Tasks before the gate contain no inference call, ML dependency, embedding, VLM, LLM, or CV model.
6. **No persistent biometric data.** Never store face embeddings, appearance embeddings, head-orientation profiles, or identity vectors for minors.
7. **Protect the footage.** Buckets stay private; signed URLs are short-lived and object-specific; raw video expires after 90 days.
8. **Ship the smallest correct thing.** A single seekable 720p MP4 is the MVP coach playback format. Do not add HLS, Redis, Celery, GraphQL, Kubernetes, native apps, or microservices without an approved ADR.

If a task conflicts with rules 1–4, stop and report the conflict. Do not implement around it.

## Decided stack

| Layer | Decision |
|---|---|
| Web | Next.js App Router, TypeScript, Tailwind CSS |
| API | FastAPI, Python 3.11, SQLAlchemy 2, Pydantic 2 |
| Database | Postgres 16 on Supabase; non-exposed `app` schema; Alembic migrations |
| Authentication | Supabase Auth magic links; Next.js owns secure session cookies |
| Browser/API boundary | Same-origin Next.js BFF forwards bearer tokens to FastAPI |
| Object storage | Private Cloudflare R2 through the S3 API |
| Video | ffmpeg to seekable H.264/AAC MP4; separate player clip exports |
| Background work | Postgres job table with `FOR UPDATE SKIP LOCKED` |
| Email | Resend |
| Hosting | Vercel for web; Fly.io for API and CPU worker |
| Deferred GPU | Manual RunPod Secure Cloud batch only |

## Source of truth

- Product behavior: `docs/01-product.md`
- Architecture: `docs/02-architecture.md`
- Data model: `docs/03-schema.md`
- API: `docs/04-api.md`
- Screen behavior: `docs/05-ui.md`
- Visual implementation: `docs/09-frontend-design-system.md`
- Security: `docs/10-security-privacy.md`
- Tests and release gates: `docs/11-testing-quality.md`
- Build sequence: `docs/06-tasks.md`

When documents disagree, `docs/00-decisions.md` wins, then this file, then the more specific numbered document. Record any new non-obvious decision as a short ADR in `docs/decisions/`.

## Task workflow

Before work:

- Confirm the task's prerequisites are complete in `STATUS.md`; do not treat stubs as complete.
- State the files and tests the task will touch.
- Ask one targeted question if a missing choice changes behavior, security, or schema.

During work:

- One task per branch and one writer per checkout.
- Keep changes within the task. Do not opportunistically redesign adjacent systems.
- Add no production dependency without recording why the platform cannot do the job safely without it.
- Any schema change uses Alembic and includes RLS in the same task.
- Product tables stay outside Supabase Data API exposed schemas; do not weaken this boundary to work around a permission error.
- Public API types come from the FastAPI OpenAPI document; never hand-write duplicate TypeScript API types.
- Update `STATUS.md` when the task is finished, blocked, or materially changed.

Before handoff:

- Run the task's named tests plus lint and type checks for touched packages.
- Review the diff for privacy leaks, authorization gaps, data loss, and scope creep.
- Report changed files, commands run, results, remaining risks, and the next eligible task.

## Engineering conventions

**Python:** ruff format/lint; public functions typed; routers call service functions; SQLAlchemy models, Pydantic schemas, and services stay separate.

**TypeScript:** Biome; Server Components by default; client components only for actual browser interactivity; generated API types only.

**SQL:** product tables in `app`, helpers in `private`; snake_case; every foreign key indexed; `timestamptz`; in-video offsets are integer `*_ms` relative to the original file; UUID primary keys; explicit checks for bounded values.

Use these domain words exactly: `observation`, `judgment`, `review_publication`, `player_reflection`, `development_goal`, `evidence_clip`. Do not rename them to review, feedback, insight, score, or annotation.

## Load-bearing tests

Never skip, weaken, or mark these expected-failure:

1. Player A cannot read Player B's published judgment or clip at the database and API layers.
2. Five marked draft clips survive reload and network failure.
3. A published player URL cannot retrieve the coach playback object or any other clip.
4. A frozen SoccerMaster artifact produces deterministic candidate observations once CV exists.

## Player-facing copy

- Render `applied` as “You did this.”
- Render `opportunity` as “Chance to do this.”
- Never show `not_relevant` to players.
- Avoid “failed,” “weak,” “incorrect,” “performance score,” “insights,” “unlock,” “level up,” “elite,” and “AI-powered.”
- Reflections are optional and never gate the next clip.
- No badges, streaks, nudges, or engagement pressure.

## External CV code

SoccerMaster remains outside this repository. As of the research date its public repository has no license file. Do not vendor, redistribute, publish, or deploy its code or weights. The integration is a private research adapter that consumes and emits files. Recheck licensing before Phase D and before any public deployment.
