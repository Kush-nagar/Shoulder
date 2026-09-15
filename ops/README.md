# Autonomous build system

The control plane that executes the canonical Shoulder backlog in the cloud.
Architecture and the reasoning behind it: [ADR 0019](../decisions/0019-autonomous-build-system.md).

## Layout

| Path | What it is | Lives on |
|---|---|---|
| `ops/policy.json` | Routing, budgets, limits, privacy, **human gates**. Edit this to change behaviour. | `main`, reviewed |
| `ops/state/progress.json` | Task completion ledger | `agentops-state` |
| `ops/state/models.json` | Discovered model catalogue and qualification verdicts | `agentops-state` |
| `ops/state/providers.json` | Per-lane health | `agentops-state` |
| `ops/state/tasks.json` | Active task leases, checkpoints and repair counters | `agentops-state` |
| `ops/state/budget.json` | Recorded API spend | `agentops-state` |
| `services/agentops/` | The orchestrator itself | `main`, reviewed |
| `.github/workflows/agentops-*.yml` | Coordinator, worker, reviewer, watchdog, pull-request reaction | `main`, reviewed |

Do not edit the orchestrator to change routing. Change `ops/policy.json`.

## Where runtime state lives

**Nothing in normal operation pushes to the default branch.**

Leases, provider health, spend and progress change many times per task. They
used to be committed straight to `main`, which only works if that branch is
unprotected, or protected with a bypass actor for GitHub Actions. This is a
personal repository, and its rulesets offer no such actor to grant: with
protection on, every ledger write was rejected with `GH013` and the loop could
not run at all.

So the mutable ledger moved to its own branch:

```
main                 product code, policy, workflows, human gates
                     protected: quality + verdict, reviewed pull requests only

agentops-state       ops/state/*.json and nothing else
                     an orphan branch; no product code has ever been on it
```

Every job that touches state does the same two things:

```
python -m services.agentops.cli state-pull     # before reading anything
python -m services.agentops.cli state-push --message '...'   # after mutating
```

`state-contents` lists what the branch holds and exits non-zero on any path
outside `ops/state/`.

### Why it cannot carry anything else

The commit is not made by switching branches. It is built from a throwaway
index containing exactly one directory:

```
GIT_INDEX_FILE=$tmp git read-tree --empty
GIT_INDEX_FILE=$tmp git add --all -- ops/state
GIT_INDEX_FILE=$tmp git write-tree      ->  git commit-tree  ->  git push
```

Nothing else in the worktree can reach that tree. It is a property of how the
commit is constructed rather than a rule someone has to remember — which
matters, because the branch-switching dance this replaced was itself the source
of several bugs, including a worker that could push task-branch content to
`main`.

### Concurrent writers

`pull` records the commit it read. `push` makes that commit the parent and
pushes without any force, so git's own fast-forward rule rejects it when
another writer has landed in between. On a rejection the caller re-reads the
branch and re-applies **only the files it changed**, leaving everything else at
the other writer's version.

Two writers changing the *same* file is the case that cannot be merged, and
there the last writer wins. So the callers whose mutation is one cheap command
— the worker and the pull-request reaction — re-run the mutation against
freshly pulled state instead of relying on that. The coordinator cannot:
acquiring a lease increments an attempt counter, and re-running it would spend
a task's attempt budget on a push race.

### The copies still committed on main

`ops/state/*.json` on the default branch are the **seed**. Before the branch
exists, `state-pull` leaves them in place and the first `state-push` turns them
into the branch; after that the branch is authoritative and the committed
copies are historical. That is also what makes a fresh clone and a migrating
repository take exactly one path, with no separate migration step.

### Human gates are not in the ledger

`gates.real_use_gate` lives in `ops/policy.json`, on the protected branch.
The ledger is written by automation without review, so a gate stored there
would be a gate the system could open for itself — and this one is what stands
between autonomy and the machine-learning phases AGENTS.md rule 5 forbids.
`state.gate_passed` reads policy only; a ledger may still *refuse* a gate,
never grant one.

### STATUS.md

Not written by automation any more, for the same reason: it is on the protected
branch. The live picture is the Control Center issue, and workers read progress
from the ledger through their brief rather than from the file. A human, or a
reviewed pull request, can regenerate its block with `cli status-snapshot`.

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

| Lane | Harness | Billing | Priority | May write frontend |
|---|---|---|---|---|
| `claude_subscription` | Claude Code action | Claude subscription | 1 | yes |
| `codex_cloud` | `@codex` mention | ChatGPT subscription | 2 | yes |
| `openrouter` | Claude Code action via OpenRouter | OpenRouter credits | 3 | **no** |
| `codex_api` | Codex action | OpenAI API | 4 (disabled) | yes |

Claude is the primary writer for both halves of a task. That changed on
2026-09-14: frontend work used to be Codex-only, which meant every canonical
task containing UI stalled the autonomous loop waiting for a second provider.
Claude now writes the interface a task requires, bounded to *functional*
completeness — real data flow, states, keyboard operation, labels and roles,
phone width, and the task's named tests. Visual polish is a separate later
pass and the brief says so explicitly.

The OpenRouter restriction is unchanged: that lane never writes frontend. If
both permitted lanes are down, frontend tasks report `BLOCKED_PROVIDER` rather
than falling back to a forbidden writer.

## How the loop closes

Each stage hands to the next through GitHub, not through a conversation, so any
stage can be resumed by a fresh run that reads only repository state.

```
merge to main ─▶ coordinator ─▶ worker ─▶ pull request
                     ▲                        │
                     │                        ▼
                 reconcile ◀── merge ◀── Quality + review verdict
                                              │ (failed)
                                              ▼
                                        agentops-pr ─▶ repair worker
```

**Nothing in this repository merges a pull request.** GitHub's own auto-merge
does, once every required branch-protection context passes. The worker enables
it when it opens the pull request; the watchdog re-arms it on any open
autonomous pull request that has none, which is the recovery path for a worker
that died between opening the pull request and arming the merge. No workflow
polls for green and no runner is held open waiting for a check that outlasts
it.

The required contexts are:

| Context | Workflow | What it proves |
|---|---|---|
| `quality` | `ci.yml` | format, lint, types, tests, contracts, build, browser smoke |
| `verdict` | `agentops-review.yml` | independent review left nothing unresolved |

`verdict` is counted, not judged: unresolved, non-outdated review threads plus
each reviewer's **latest** review state. It fails closed — a review state that
cannot be read blocks the merge rather than passing it. It reports on every
pull request including a human's, because a required context that never runs
leaves one pending forever.

Three things it deliberately does not do:

- **Count review history.** A reviewer that requested changes and then approved
  the repaired branch would otherwise stay blocking forever, so the branch
  could never go green and the repair ceiling would be spent on nothing.
- **Count outdated threads.** A pushed repair makes every earlier thread
  outdated; counting them would keep the branch red whatever the repair fixed.
- **Trust a mention-based reviewer's job result.** Codex Cloud answers minutes
  after the job that asked it finishes, so "not looked at yet" and "reviewed
  and clean" are the same picture. For a `github-mention` reviewer the verdict
  stays `pending` until a review is submitted against the current head commit,
  and `pull_request_review` re-derives it when that review lands.

`agentops-pr.yml` reacts to a failing required check on an autonomous branch by
taking a repair cycle and dispatching the **same** writer again with a repair
brief. A failing test is a code problem, not a provider problem, so a repair
never spends fallback capacity and never spends an implementation attempt. The
two ceilings — `max_ci_repair_cycles` and `max_review_repair_cycles` — are
independent, and when one is spent the task is released as blocked instead of
retried forever.

### The liveness cost of failing closed

An unresolved review thread blocks the merge, and the gate cannot tell "already
fixed" from "ignored". Changing the lines a finding points at marks its thread
outdated and it stops counting, which covers most repairs — this pull request
went from fourteen blocking threads to six that way. A fix made *elsewhere*
leaves its thread standing, and the branch then stays blocked for every
remaining repair cycle until the task is released as blocked.

That is deliberate. The alternative — dropping findings from older commits —
merges on the assumption that a silent reviewer means a fixed problem, and gets
it wrong in the direction that ships the defect. Blocking is wrong in the
direction that stops and asks, which is the trade this system is supposed to
make.

The repair brief therefore tells the writer to reply to and resolve each thread
it answers, and gives it the exact `gh api graphql` calls. If that does not
happen, the task blocks visibly on the Control Center rather than merging
something unreviewed.

It separates a reviewer that *found* something from a reviewer that *could not
run*. Only the first is a repair; the second reruns the reviewer and spends no
cycle, because a writer handed no finding pushes no commit, which emits no
`synchronize`, which leaves the pull request stuck on the original failed check
forever.

It also requires the failing run's head repository to be this repository. On a
public repository anyone may open a fork pull request named after the live
canonical branch and fail a check deliberately; repair lookup is by task
number, so without that check such a run would spend the real task's repair
budget and point a credentialed worker at the real branch.

## Watching it

`cli control-center` rewrites the body of one issue, **Shoulder AgentOps
Control Center**, on every meaningful transition: autonomy status, current task
and stage, provider and model, checks, last durable checkpoint, repair counts,
next eligible tasks, blocked tasks, and the real gates. The activity feed issue
stays a feed — event comments — because a page that answers "what is happening
now" and a log that answers "what happened at 03:14" are different things.

## Secrets

Set through `gh secret set NAME`, which reads the value without echoing it.
Never paste a credential into a file, a log, an issue, or a chat.

| Secret | Lane | Needed for |
|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | Claude | Backend work and review. From `claude setup-token`. |
| `OPENROUTER_API_KEY` | OpenRouter | Backend overflow, cheap mechanical work, independent review, model qualification. |

### One owner action this system cannot do for you

The OpenRouter lane's retention and training policy is configured on the
OpenRouter **account**, not per request: the coding harness does not send
`provider.zdr`, so only the account setting governs real traffic. This
repository cannot read that setting, so the lane stays ineligible until you
confirm it:

1. In OpenRouter privacy settings, disable prompt logging/training and restrict
   routing to zero-data-retention providers.
2. Record it:

```
python -m services.agentops.cli confirm-privacy --lane openrouter   --note "ZDR-only routing and training disabled in account privacy settings"
```

Until then, backend overflow to OpenRouter is refused rather than assumed safe.
Shoulder handles minors' data, so the unconfirmed state fails closed.

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

## Verified in the cloud

These were proven by real runs, not asserted. The provider credentials exist
only inside Actions, so `agentops-verify.yml` is where the proof happens.

| What | How it was proven |
|---|---|
| Live catalogue | A discovery run parses the real OpenRouter catalogue. |
| OpenRouter lane | Real probe requests under the privacy contract, with recorded cost. |
| Claude lane | A real `claude-code-action` run authenticating with the subscription token. |
| Codex Cloud lane | A real `@codex review` on a pull request, answered by Codex. |
| Activity feed | The cloud run posts its own result to the feed issue. |
| Coordinator | A dry run against real state, asserting autonomy is still off. |

Re-run it any time with:

```
gh workflow run agentops-verify.yml
```

It costs a fraction of a cent, records that spend against the ceilings, and
cannot open a pull request, merge anything, or enable autonomy.
