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
| `.github/workflows/agentops-*.yml` | Coordinator, worker, watchdog |

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
python -m services.agentops.cli qualify --lane openrouter
python -m services.agentops.brief --task 14 # see exactly what a worker receives
python -m services.agentops.watchdog        # recovery sweep
```

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
| `OPENAI_API_KEY` | Codex | All frontend work. |
| `OPENROUTER_API_KEY` | OpenRouter | Backend overflow, cheap mechanical work, independent review, qualification runs. |

## Budgets

Ceilings live in `ops/policy.json` under `budget` and start at $5/day and
$40/month per API lane. The orchestrator never raises a ceiling by itself. On
exhaustion it checkpoints, marks the lane `BUDGET_EXHAUSTED`, and routes to
another authorised lane or blocks.

The Claude subscription lane is never blocked by a budget ceiling, because it
does not spend API money.

## How a task flows

```
merge to main
  -> coordinator: refresh catalogue, evaluate backlog, classify, route, lease
  -> worker: one branch, implement, run ./scripts/check.ps1, open a PR
  -> independent reviewer from a different provider family
  -> CI
  -> merge
  -> coordinator again
```

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
