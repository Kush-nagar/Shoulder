# AgentOps local runtime — design

Date: 2026-09-16. Scope: add the missing local execution layer around the
existing AgentOps modules. Nothing in `coordinator`, `routing`, `classify`,
`catalog`, `leases`, `brief`, `governance`, `watchdog`, `reconcile` or
`control_center` changes.

## Problem

Every writer path today runs in GitHub Actions through
`anthropics/claude-code-action`. There is no code that creates a worktree,
starts a local headless Claude worker, runs verification, or shows what is
happening. Cloud autonomy stays off; the local layer is what is missing.

## Constraints (settled, not reopened)

1. `ops/policy.json` is unchanged. `max_parallel_writers` stays 1; the runtime
   reads the limit and must work unchanged when it becomes 2.
2. OpenRouter is implemented but inert without `OPENROUTER_API_KEY` in the
   process environment. The key is never persisted, printed, logged, or put in
   state. Absence is `AVAILABLE_LATER`, not a failure. No paid call.
3. uv is resolved deterministically and version-verified against the repo pin.
   No machine path is committed.
4. Local runtime state lives in ignored `.agentops/local/`. Tracked
   `ops/state/*.json` is read-only baseline. No push to `agentops-state`.
5. Task 15 is not started.

## Components

| File | Purpose | Depends on |
|---|---|---|
| `services/agentops/localstate.py` | ignored runtime store: config, workers, events, usage, atomic writes, redaction | stdlib |
| `services/agentops/toolchain.py` | pinned-uv resolver, verification commands, cross-process infra lock | localstate |
| `services/agentops/local.py` | worktree lifecycle, headless Claude executor, run loop, recovery | coordinator, leases, brief, governance, toolchain, localstate |
| `services/agentops/dashboard.py` | read-only stdlib HTTP server on 127.0.0.1:4317 | localstate, control_center |
| `services/agentops/cli.py` (edit) | `run`, `serve`, `resume`, `provider`; `status` gains a `local` block | above |
| `scripts/agentops-local.ps1` | start / stop / status / resume | cli |
| `scripts/agentops-provider.ps1` | claude / openrouter | cli |

### Runtime store — `.agentops/local/`

```
config.json      provider choice, resolved uv path, worktree root, role budgets
runtime.json     coordinator pid, host, started_at, state
workers.json     per-task worker records (pid, image, branch, worktree, phase,
                 model, lane, role, started_at, last_event, usage)
events.jsonl     append-only structured event stream
locks/infra.lock cross-process verification lock (pid + started_at + host)
runs/<run_id>/   stdout.jsonl, stderr.log, brief.md, result.json
```

Leases keep using the existing `leases` module logic, but the local runtime
holds them in `.agentops/local/leases.json`, seeded from tracked
`ops/state/tasks.json` and never written back to it. Tracked state stays clean,
so a worker branch is never dirtied by runtime bookkeeping.

### Pinned uv resolution

Pin is parsed from `pyproject.toml` `required-version = "==X.Y.Z"`. Candidates,
in order: `SHOULDER_UV_PATH`; `config.json` `uv_path`; repo `.tools/uv{,.exe}`;
`.tools/uv{,.exe}` in each `git worktree list` entry and in the common-dir
parent; `uv` on PATH. Every candidate is executed with `--version` and rejected
unless it equals the pin. First match is cached to `config.json`. No candidate
means a fail-fast error naming the pin, what was tried, and how to fix it.

### Verification

Two kinds:

- `fast` — ruff format/check, mypy, `unittest discover -s tests`. No shared
  ports. Runs unlocked.
- `gated` — `scripts/check.ps1` (starts a web server for the smoke suite) and
  every `scripts/check-*.ps1` (Docker, Supabase CLI, MinIO on fixed ports).
  Requires the infra lock.

The lock is an `O_CREAT|O_EXCL` file holding pid, image name, host, and
`started_at`. It is stale when the owner process is gone or the TTL has passed;
a stale lock is recorded and taken, never silently deleted. Liveness never uses
`os.kill(pid, 0)` — on Windows that terminates the process. Windows uses
`tasklist` filtered by pid plus an image-name match; POSIX uses signal 0.

### Worker execution

```
claude -p --model <assignment.harness_model>
        --output-format stream-json --verbose
        --permission-mode acceptEdits --permission-prompts none
        --max-turns <role budget>
        --add-dir <worktree>
```

Superseded: writable roles now use `--dangerously-skip-permissions` and
read-only roles use `--permission-mode plan --permission-prompts none`. See
`docs/agentops-local-runtime.md`.

cwd is the worktree. The prompt is the existing `brief.render()` packet plus a
short skill-routing line. `--verbose` is mandatory with `stream-json`. The hard
stop is a wall-clock timeout, because `--max-turns` is undocumented in CLI
2.1.268 and cannot be relied on alone. `bypassPermissions` is never used.
Every stream event is appended to the run log; `result` supplies
`total_cost_usd`, `usage`, `stop_reason`, `session_id`.

OpenRouter changes only the child environment:
`ANTHROPIC_BASE_URL=https://openrouter.ai/api`, `ANTHROPIC_AUTH_TOKEN` from
`os.environ`, `ANTHROPIC_API_KEY` emptied. The key is read at spawn time and is
never part of any record the runtime writes.

### Roles and budgets

Roles map to the existing routing output rather than a second router. Writer and
reviewer models come from `coordinator.plan()`. `scout` and `summarize` are
read-only helper roles pinned to the cheapest qualified Haiku-class model
through the same `routing` call with a CHEAP_MECHANICAL classification. Turn and
timeout budgets per role live in `config.json` with in-code defaults.

### Run loop

`agentops run` refuses while `autonomy.enabled` is false unless `--dry-run` is
given, so bootstrap can exercise the lifecycle without dispatching product work.
Each iteration: load context, pick the next eligible candidate, plan, acquire a
lease (existing module, existing writer cap), create the worktree and branch,
run the writer, classify the outcome, run verification, record, release or
escalate within the existing ceilings. Governance is checked against the diff
before any completion is recorded; a violation fails the run.

### Recovery

On start, the runtime reads `workers.json`, checks each recorded pid for
liveness, inspects the worktree and branch, and classifies each worker as
`running`, `interrupted`, or `finished`. Interrupted work keeps its worktree and
branch; the lease is recovered through the existing stale-lease path. Nothing is
deleted automatically.

### Dashboard

`agentops serve` binds 127.0.0.1:4317. `GET /` renders small vanilla HTML/CSS:
coordinator status, current task, queue, active worker cards (role, model,
lane/provider, task, branch, worktree, phase, elapsed, last action, verification
state), recent events, failures and escalations, usage. `GET /state` returns the
same data as JSON. Everything else answers 405. Meta refresh every 5s. No
WebSockets, no framework, no database, no mutation path.

## Testing

Focused unit tests: worktree isolation, one writer per task, writer cap,
runtime state outside tracked `ops/state`, `.agentops` ignored, success and
failure classification, interrupted and stale-process recovery, verification
failure blocking completion, infra lock acquire/stale-recovery, governance
refusal, model passed through to the executor argv, Fable never selected,
missing OpenRouter key leaving Claude working, OpenRouter env built safely,
secret never reaching logs/state/dashboard, uv resolver rejecting a wrong
version and accepting a correct one, dashboard read-only, turn budget in argv,
escalation ceilings. All 481 existing AgentOps tests must stay green.

## Dry run

A synthetic non-product task: its own worktree and throwaway branch, one real
harmless headless Claude call that writes a scratch file inside that worktree,
structured events, completion classification, the fast verification suite,
dashboard visibility, then cleanup. It never touches product code, never pushes,
and never runs Task 15.
