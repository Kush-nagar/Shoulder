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
| Model approval | `./scripts/agentops-local.ps1 models` |
| Evaluate candidates | `./scripts/agentops-local.ps1 evaluate -Models deepseek/deepseek-v3` |
| Stop | `./scripts/agentops-local.ps1 stop` |
| Status | `./scripts/agentops-local.ps1 status` |
| Resume after a crash | `./scripts/agentops-local.ps1 resume` |
| Dashboard | `./scripts/agentops-local.ps1 dashboard` → <http://127.0.0.1:4317/> |
| Smoke the whole path | `./scripts/agentops-local.ps1 dry-run` |
| Provider | `./scripts/agentops-provider.ps1 claude` / `openrouter` / `status` |

Each wrapper maps arguments onto `python -m services.agentops.cli`, which can be
called directly: `run`, `serve`, `stop`, `resume`, `local-status`, `doctor`,
`dry-run`, `provider`.

## Two permissions, not one

Cloud autonomy and local execution have different blast radii, so they have
different switches.

| | Where it lives | State | Who sets it |
|---|---|---|---|
| Cloud autonomy | `ops/policy.json` (`autonomy.enabled`) | **off** | a human, in a reviewed pull request |
| Local execution | `.agentops/local/config.json` (`local_enabled`) | off until started | the operator, by running `start` |

Typing `./scripts/agentops-local.ps1 start` *is* the local authorisation: it is
recorded in ignored local state and never touches `ops/policy.json`. `stop`
withdraws it. Importing a module does not set it, and neither does loading the
dashboard, which is why neither can start work. The cloud `dispatch` path still
reads the cloud switch and still refuses.

## What a run does

1. `coordinator` picks the next eligible task from `docs/06-tasks.md`.
2. `classify` and `routing` pick the capability class, lane, model and effort.
3. `leases` takes an exclusive lease, enforcing `max_parallel_writers`.
4. A worktree and branch are created under `D:\Shoulder-agents`.
5. `brief.render()` builds the packet; one line names the capabilities for the
   role.
6. A headless Claude worker runs in that worktree.
7. The diff is checked against `governance`, then targeted verification runs.
8. A reviewer -- chosen by the same router, in plan mode so it cannot edit --
   reads the diff and the canonical requirements and answers with structured
   findings.
9. Blocking findings (severity `blocker` or `major` at `high` or `medium`
   confidence) go to a repair worker with the exact findings, then targeted
   verification and review run again. A `nit` at `low` confidence is recorded
   and does not block.
10. Full verification runs, governance is rechecked, and only then does the task
    reach `ready_for_pr`.

Every judgement about what a task changed is a range from the commit the
worktree was on before the worker started, recorded once and never moved. That
survives the worker committing, a repair committing on top, a restart and a
dashboard read, so a committed change to a guarded path cannot hide from the
governance check and a reviewer cannot be handed an empty diff.

Outcomes: `ready_for_pr`, `verification_complete_unreviewed`,
`verification_failed`, `implementation_failed`, `timeout`,
`governance_refused`, `blocked`. `--no-review` is a diagnostic: it can reach
`verification_complete_unreviewed` and never `ready_for_pr`. A task in either
of those states is finished as far as this runtime is concerned and is not
handed to another worker. Repairs are bounded by the existing
`max_review_repair_cycles` and `max_implementation_attempts` ceilings; when a
budget runs out the task is `blocked` with the unresolved findings named.

Local review is same-family when no other provider family is installed, and is
labelled that way in the record and on the dashboard. The independent review
still happens in the cloud on the pull request.

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
- `gated` — the worktree's own `scripts/check.ps1`. It starts a web server,
  Supabase and MinIO on fixed ports, so exactly one runs at a time behind
  `.agentops/local/locks/infra.lock`. Both kinds run with the task worktree as
  the working directory, so what is verified is the branch and never the
  coordinator's checkout.

The lock is held by at most one process. Its record is published atomically, so
a concurrent reader never sees a half-written holder; a holder that has provably
stopped -- or has run past the ceiling -- can be taken by exactly one
contender; an unreadable record from a live holder fails closed; and release
only removes a lock that is still ours, so an overrunning holder cannot delete
its successor's claim.

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

## Harnesses and providers

Routing chooses the model. The lane it chose decides which harness runs it.

| Lane | Harness | Models |
|---|---|---|
| `claude_subscription` | Claude Code (`claude -p`) | Anthropic, on the subscription |
| `openrouter` | OpenCode (`opencode run`) | DeepSeek, GLM, Kimi, Qwen and other OpenRouter models |

The provider setting constrains which lanes routing may choose:
`claude` permits only the subscription lane, `openrouter` only the OpenRouter
lane, and `auto` lets both compete on the existing policy priority. A selected
provider that cannot run blocks the task rather than quietly falling back to
the other one.

Non-Anthropic models are **not** pushed through Claude Code's Anthropic
compatibility endpoint. That harness is tuned for one family's tool protocol,
and judging another family on it measures the scaffolding rather than the model.

### One-time OpenRouter setup

Two things are needed, and neither is done automatically:

```powershell
npm install -g opencode-ai                 # the harness; verified Windows path
$env:OPENROUTER_API_KEY = '<key>'          # this shell only; never committed
./scripts/agentops-provider.ps1 openrouter # records the choice, not the key
./scripts/agentops-provider.ps1 status     # expect status: AVAILABLE
./scripts/agentops-local.ps1 doctor        # both harnesses reported
```

Until both are present, OpenRouter reports `AVAILABLE_LATER` with the reason,
native Claude keeps working, and the router simply does not choose that lane.

The key is read from the process environment at spawn time by OpenCode itself,
through a per-run config that contains `{env:OPENROUTER_API_KEY}` rather than
the key. It never reaches argv, configuration, state, a log, or the dashboard.

To go back: `./scripts/agentops-provider.ps1 claude`.

### About Ori

OpenRouter's own Ori CLI configures Claude Code, Codex, OpenCode and Hermes for
OpenRouter. It is not on this path: its documented installer is a bash script,
it authenticates with OAuth rather than the environment key this runtime is
built around, and it publishes no non-interactive usage. If it grows a Windows
installer and a headless mode, it would slot in as a third executor.

## Model approval

The catalogue discovers everything OpenRouter serves, and the cheapest
qualifying model is what a cost-ordered router reaches for. Approval is the
deliberate step in between:

| State | May do |
|---|---|
| `DISCOVERED` | nothing (the default for every new model) |
| `CANARY` | evaluations and throwaway work only |
| `APPROVED` | real tasks |
| `DISABLED` | nothing |

High-risk classes (`FRONTIER_REASONING`, `LONG_HORIZON_AGENT`) additionally
require `--risk-class high`. Anthropic models on the subscription lane keep the
behaviour `ops/policy.json` already gives them.

```powershell
./scripts/agentops-local.ps1 models
python -m services.agentops.cli approve-model deepseek/deepseek-v3 CANARY
./scripts/agentops-local.ps1 evaluate -Models deepseek/deepseek-v3
python -m services.agentops.cli approve-model deepseek/deepseek-v3 APPROVED
```

`evaluate` runs one fixed throwaway task per model on its own branch and reports
completion, unnecessary edits, governance violations, tests, turns, latency,
tokens and cost -- the same task and harness for each, so the numbers compare.
It is deliberately small. OpenRouter's Ori Eval is the larger tool for this
(`.eval.ts` files run with Bun); it is documented here rather than depended on.

## Recovery

A local process can die. On `resume`, each recorded worker is classified from
its pid, its worktree and its branch as `running`, `interrupted`, or `finished`.
An interrupted worker keeps its worktree and branch — the partial implementation
is in there — and its lease is reclaimed through the existing stale-lease path,
which refuses to take a lease from an owner that is still running.

## Worker command lines

```
claude -p --model <routed model> --output-format stream-json --verbose
       --permission-mode acceptEdits --permission-prompts none
       --max-turns <role budget>  <prompt>

opencode run --model openrouter/<vendor>/<model> --format json
             --dir <worktree> --auto  <prompt>
```

Notes that cost time to learn:

- `stream-json` under `--print` **requires** `--verbose`.
- `--add-dir` is variadic and will swallow the prompt that follows it. The
  worktree is the working directory, so it is not passed.
- `--max-turns` is accepted but undocumented in CLI 2.1.268, so the wall-clock
  timeout per role is the bound actually relied on.
- `--dangerously-skip-permissions` is never used. `--permission-prompts none`
  denies what would have prompted instead of waiting for a human.
- The wall-clock timeout is enforced by a timer, not by the output loop, and
  terminates the process tree. A worker that produces nothing and hangs is
  stopped at its deadline.
- On a subscription, `total_cost_usd` in the result event is a reported figure,
  not a billed one. The dashboard says so rather than printing it as money.
  OpenRouter costs are real and are shown as billed.
- A reviewer runs in `--permission-mode plan` (Claude Code) or with `edit` and
  `bash` denied (OpenCode), so it reports findings instead of quietly fixing
  them.
- OpenCode's event schema is not published, so the reader accepts JSON lines, a
  single JSON document, or an array, and classifies the run by exit code.
