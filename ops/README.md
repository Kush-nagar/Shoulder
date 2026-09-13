# Autonomous build system

The control plane that executes the canonical Shoulder backlog in the cloud.
Architecture and the reasoning behind it: [ADR 0019](../decisions/0019-autonomous-build-system.md).

## Layout

| Path | What it is |
|---|---|
| `ops/policy.json` | Routing, budgets, limits, privacy. **Edit this to change behaviour.** |
| `ops/state/progress.json` | Canonical task completion ledger |
| `ops/state/models.json` | Discovered model catalogue and qualification verdicts |
| `ops/state/providers.json` | Per-lane health |
| `ops/state/tasks.json` | Active task leases and checkpoints |
| `ops/state/budget.json` | Recorded API spend |
| `services/agentops/` | The orchestrator itself |
| `.github/workflows/agentops-*.yml` | Coordinator, worker, reviewer, watchdog |

Do not edit the orchestrator to change routing. Change `ops/policy.json`.

## Stopping it

```
gh variable set AUTONOMY_ENABLED --body false
```

That is the emergency stop. It needs no commit and no source change. Workers
already running finish their current step and stop; nothing new is dispatched.
The watchdog keeps its read-only sweep and will not restart work.

## Running it by hand

All commands are safe except `dispatch`, which refuses while autonomy is off.

```
python -m services.agentops.cli status      # ledger, health, qualified models
python -m services.agentops.cli plan        # dry-run the next task selection
python -m services.agentops.cli discover    # refresh the model catalogue
python -m services.agentops.cli health --probe   # lift lanes whose secret exists
python -m services.agentops.cli qualify --lane openrouter
python -m services.agentops.cli verify-assignment --task 14 --lane codex_api --model gpt-5-mini
python -m services.agentops.cli spend --lane openrouter --usd 0.02 --task 14
python -m services.agentops.brief --task 14 # see exactly what a worker receives
python -m services.agentops.watchdog        # recovery sweep
```

`health --probe` is what lifts a lane out of its seeded `UNAVAILABLE` state: it
promotes a lane only when that lane's secret is actually present in the
environment. The coordinator runs it before planning, so adding a secret is
enough — no state file needs editing by hand.

`reviewer` prints the independent reviewer for a task, chosen from a different
provider family than the writer. `agentops-review.yml` runs it on every pull
request from a branch this system created.

`verify-assignment` is the worker's own check. Dispatch inputs are
caller-controlled, so before doing any work the worker re-derives the policy
decision and exits non-zero if what it was handed disagrees. A hand-dispatched
run cannot route frontend work to a forbidden lane or name an unqualified
model.

## Lanes

| Lane | Harness | Billing | May write frontend |
|---|---|---|---|
| `claude_subscription` | Claude Code action | Claude subscription | no |
| `codex_api` | Codex action | OpenAI API | **yes, only this one** |
| `openrouter` | Claude Code action via OpenRouter | OpenRouter credits | no |

Frontend implementation is written by the OpenAI lane or it does not happen. If
that lane is unavailable, frontend tasks report `BLOCKED_PROVIDER` rather than
falling back to a forbidden writer.

## Secrets

Set through `gh secret set NAME`, which reads the value without echoing it.
Never paste a credential into a file, a log, an issue, or a chat.

| Secret | Lane | Needed for |
|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | Claude | Backend work and review. From `claude setup-token`. |
| `OPENROUTER_API_KEY` | OpenRouter | Backend overflow, cheap mechanical work, independent review, model qualification. |

**Codex Cloud needs no secret.** It is reached through the Codex GitHub
integration: the coordinator opens a task branch and pull request and comments
`@codex <instruction>`, and the work runs in OpenAI's sandbox against the
ChatGPT allowance. Setup is account-level rather than a repository credential:
connect the repository in Codex cloud and turn on code review at
`chatgpt.com/codex/settings/code-review`.

`OPENAI_API_KEY` is **not** required. The optional `codex_api` lane is disabled;
enabling it is a deliberate decision to add pay-per-use API billing.

### What the Codex lane cannot do

- A mention carries no model or effort, so the tier the router picks is
  advisory and the account's configured Codex model runs. Assignments carry
  `model_enforced: false`.
- Consumer plans expose no usage API, so remaining allowance cannot be read.
  Exhaustion is inferred from a run that could not proceed:
  `cli exhausted --lane codex_cloud` cools it for its five-hour window, backend
  work overflows to OpenRouter, and frontend work waits.

## Budgets

Ceilings live in `ops/policy.json` under `budget` and start at $5/day and
$40/month per API lane. The orchestrator never raises a ceiling by itself. On
exhaustion it checkpoints, marks the lane `BUDGET_EXHAUSTED`, and routes to
another authorised lane or blocks.

Spend is recorded per lane per day, per month, and per task. A task that has
used its `per_task_usd` ceiling stops being an eligible candidate, so a task
cannot burn the monthly budget across repeated attempts.

**The Codex lane's spend is not tracked.** `openai/codex-action` reports only
its final message, with no usage or cost, so there is nothing to record. The
Claude Code harness does report usage, so the Claude and OpenRouter lanes are
tracked accurately. Until that changes, watch OpenAI API spend in the
provider's own dashboard, and keep `max_parallel_writers` low.

The Claude subscription lane is never blocked by a budget ceiling, because it
does not spend API money.

## How a task flows

```
merge to main
  -> coordinator: reconcile merged work, refresh catalogue, probe health,
                  evaluate backlog, classify, route, lease
  -> worker: one branch, implement, run ./scripts/check.ps1, open a PR
  -> reviewer: router-selected, different provider family, read-only
  -> CI
  -> merge
  -> coordinator again
```

Reconciliation is what closes the loop. A task is complete when the branch its
lease names has become an ancestor of `main`, which is true exactly when the
pull request merged. The coordinator then marks the task done in
`progress.json`, releases the lease, and looks for the next eligible task.

Continuation is event-driven. The hourly watchdog exists only to recover a
crashed worker, an expired lease, an elapsed provider cooldown, or a lost
continuation event.

## What it will not do

- Start Task 23 or anything later. The real-use gate is a human decision and
  `allow_phase_d_and_later` is false.
- Route frontend work to Claude or to a DeepSeek model.
- Use a model that has not passed qualification.
- Use an endpoint that cannot meet zero data retention.
- Raise a spend ceiling.
- Send production footage, player reflections, real rows, or credentials to any
  model. Agents get source, synthetic fixtures, and sanitised logs.
