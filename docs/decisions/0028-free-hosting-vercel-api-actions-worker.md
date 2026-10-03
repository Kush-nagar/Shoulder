# ADR 0028: Free hosting — API on Vercel, worker on GitHub Actions

Status: accepted, 2026-10-03. Supersedes the Fly.io rows of AGENTS.md
"Decided stack" and ADR 0021's deploy steps. The owner wants no paid hosting
until the product scales; the Fly.io trial ended and both machines stopped.

## Decision

1. **API on Vercel** (Hobby), project `shoulder-api`, production origin
   `https://shoulderapp-api.vercel.app`, region iad1 beside Supabase. Vercel
   builds Python 3.12 from `requirements.txt`, so `scripts/deploy-demo.ps1
   -Step api` uploads a staged copy: `services/api`, `services/timeline.py`,
   pins exported from `uv.lock`, and an `index.py` that imports the FastAPI
   `app`. No API code changed. Development and CI stay on Python 3.11.
2. **Worker on GitHub Actions** (`.github/workflows/worker.yml`). `python -m
   services.worker.main --drain` claims jobs until the queue has been empty
   for 90 s, then exits. Leases, retries and sweeps are unchanged.
3. **Wake-up from the database** (migration 0021). A statement-level trigger
   on `app.processing_job` calls `worker_wake.dispatch()`, which sends a
   GitHub `repository_dispatch` (`worker`) through `pg_net`. pg_net sends after
   commit, so enqueueing never waits on GitHub; any error is a warning only.
   The token is the Supabase Vault secret `worker_dispatch_token`; without it
   the trigger does nothing (local, CI). A run every 6 hours is the safety net
   and the retention sweep.
4. **Exception to the definer-owner rule.** `worker_wake.dispatch()` is owned
   by `postgres`, not `shoulder_migration`, because only that owner can read
   Vault and call `net.http_post`. It lives outside `private`, takes no
   argument, reads no row, and no runtime role can execute it or use its
   schema (`tests/test_database_worker_wake.py`).

## Consequences

- Video processing starts 30–60 s after a job is queued (runner start-up).
- Private-repo Actions minutes are limited (2,000/month free): the hourly
  `agentops-watchdog` is the largest consumer and can be disabled if needed.
- Vercel Hobby is for non-commercial use; move to paid tiers when the product
  is commercial. Fly configs were removed; Dockerfiles remain for local use.
