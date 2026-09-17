# The AgentOps local runtime

Runs a Shoulder task on this workstation, in an isolated worktree, with a
headless Claude worker, and shows what it is doing on a local page. It adds
execution and observability to the AgentOps modules that already existed; it
does not decide anything they already decide.

Cloud autonomy is unaffected and stays off. Nothing here pushes to
`agentops-state` or triggers a workflow.

## Commands

| What | Command |
|---|---|
| Check the machine is ready | `./scripts/agentops-local.ps1 doctor` |
| Start | `./scripts/agentops-local.ps1 start` (add `-Once`, `-Iterations N`, `-Verification gated`) |
| Stop | `./scripts/agentops-local.ps1 stop` |
| Status | `./scripts/agentops-local.ps1 status` |
| Resume after a crash | `./scripts/agentops-local.ps1 resume` |
| Dashboard | `./scripts/agentops-local.ps1 dashboard` → <http://127.0.0.1:4317/> |
| Smoke the whole path | `./scripts/agentops-local.ps1 dry-run` |
| Provider | `./scripts/agentops-provider.ps1 claude` / `openrouter` / `status` |

Each wrapper maps arguments onto `python -m services.agentops.cli`, which can be
called directly: `run`, `serve`, `stop`, `resume`, `local-status`, `doctor`,
`dry-run`, `provider`.

`run` refuses while `autonomy.enabled` is false in `ops/policy.json`. That file
is governance and is changed by a human, on a human's branch.

## What a run does

1. `coordinator` picks the next eligible task from `docs/06-tasks.md`.
2. `classify` and `routing` pick the capability class, lane, model and effort.
3. `leases` takes an exclusive lease, enforcing `max_parallel_writers`.
4. A worktree and branch are created under `D:\Shoulder-agents`.
5. `brief.render()` builds the packet; one line names the capabilities for the
   role.
6. A headless Claude worker runs in that worktree.
7. The diff is checked against `governance`, then verification runs.
8. The outcome is recorded: `completed`, `verification_failed`,
   `implementation_failed`, `timeout`, or `governance_refused`. Failures go back
   through the existing repair ceilings.

## Where state lives

Everything mutable is under ignored `.agentops/local/`:

```
config.json   provider choice, resolved uv path, worktree root, role budgets
runtime.json  coordinator pid and state
workers.json  per-task worker records
leases.json   the lease ledger this runtime writes
events.jsonl  structured event stream
locks/        the infrastructure verification lock
runs/<id>/    brief.md, stdout.jsonl, stderr.log, result.json
```

Tracked `ops/state/*.json` is read as the baseline and never written, so a
worker's branch is never dirtied by runtime bookkeeping.

## Verification

- `fast` — ruff format, ruff check, mypy, the Python suite. Binds nothing, so
  two workers can run it at once.
- `gated` — `scripts/check.ps1` and the `check-*.ps1` infrastructure scripts.
  These start a web server, Supabase and MinIO on fixed ports, so exactly one
  runs at a time behind `.agentops/local/locks/infra.lock`. A crashed holder
  loses the lock; the takeover is recorded.

## uv

The repository pins an exact uv (`required-version` in `pyproject.toml`) and the
PATH copy on this machine is older. The resolver looks, in order, at
`SHOULDER_UV_PATH`, `config.json` `uv_path`, the repository's `.tools/`, the
`.tools/` of every other worktree Git knows about, then PATH — and runs
`--version` on each before accepting it. No machine path is committed.

To pin it explicitly:

```powershell
$env:SHOULDER_UV_PATH = 'D:\Shoulder\.tools\uv.exe'
./scripts/agentops-local.ps1 doctor
```

## Providers

Native Claude Code is the default and needs nothing configured.

OpenRouter is implemented and stays `AVAILABLE_LATER` until a key is in the
environment of the shell that starts the runtime. The key is read at spawn time
only: it is never written to configuration, state, an event, a log, or the
dashboard.

```powershell
$env:OPENROUTER_API_KEY = '<key>'          # this shell only; never committed
./scripts/agentops-provider.ps1 openrouter # records the choice, not the key
./scripts/agentops-provider.ps1 status     # expect status: AVAILABLE
./scripts/agentops-local.ps1 dry-run       # first paid call, on a throwaway branch
```

To go back: `./scripts/agentops-provider.ps1 claude`.

## Recovery

A local process can die. On `resume`, each recorded worker is classified from
its pid, its worktree and its branch as `running`, `interrupted`, or `finished`.
An interrupted worker keeps its worktree and branch — the partial implementation
is in there — and its lease is reclaimed through the existing stale-lease path,
which refuses to take a lease from an owner that is still running.

## Worker command line

```
claude -p --model <routed model> --output-format stream-json --verbose
       --permission-mode acceptEdits --permission-prompts none
       --max-turns <role budget>  <prompt>
```

Notes that cost time to learn:

- `stream-json` under `--print` **requires** `--verbose`.
- `--add-dir` is variadic and will swallow the prompt that follows it. The
  worktree is the working directory, so it is not passed.
- `--max-turns` is accepted but undocumented in CLI 2.1.268, so the wall-clock
  timeout per role is the bound actually relied on.
- `--dangerously-skip-permissions` is never used. `--permission-prompts none`
  denies what would have prompted instead of waiting for a human.
- On a subscription, `total_cost_usd` in the result event is a reported figure,
  not a billed one. The dashboard labels it as reported.
