# AgentOps bootstrap verification

Evidence index for the autonomous build system delivered by PR #16. Architecture
and reasoning: [ADR 0019](decisions/0019-autonomous-build-system.md). Operation:
[`ops/README.md`](../ops/README.md).

This record exists so the claim "ready for autonomy" can be checked rather than
trusted. Every row names what was run and where the result lives.

## Release gate

| # | Gate | Result | Evidence |
|---|---|---|---|
| A | Full Shoulder quality gate | green | `scripts/check.ps1`: Biome format + lint + typecheck, 36 + 1 node tests, ruff format, ruff check, mypy, unittest, OpenAPI contract drift check, build, auth bundle test, Playwright smoke (3 browsers), `git diff --check` |
| B | AgentOps tests | 297 green | `python -m unittest discover -s tests -p 'test_agentops_*.py'` — backlog 33, recovery 68, routing 108, workflows 88 |
| C | Strict types and lint | green | `mypy` 50 source files, `ruff check`, `ruff format --check` |
| D | `git diff --check` | green | part of the gate above |
| E | Cloud Claude subscription smoke | proven | `agentops-verify` run 34766183451 (`workflow_dispatch`, success); `providers.json` `claude_subscription` AVAILABLE, reason "cloud smoke test passed" |
| F | Codex Cloud `@codex` round trip | proven | `providers.json` `codex_cloud.lane_qualification_evidence`; reviews from `chatgpt-codex-connector[bot]` on PR #16 |
| G | OpenRouter qualified-model smoke | proven | `deepseek/deepseek-v4-flash-0731` QUALIFIED, 5 of 5 probes, evidence in `ops/state/models.json`; spend $0.005799 recorded in `ops/state/budget.json` |
| H | OpenRouter privacy confirmation | present | `providers.json` `openrouter.privacy_confirmed` true at 2026-09-13T16:02:46Z, with the owner's note; folded into routing by `coordinator.routing_inputs` |
| I | Provider failover | green | `test_agentops_routing.py`: lane unavailable falls back, degraded lane leaves the pool, cooldown expiry returns a lane, every lane unavailable blocks safely, fallback chain recorded |
| J | Lease, concurrency, recovery | 68 green | `test_agentops_recovery.py`: exclusivity, parallel-writer ceiling, heartbeat staleness, checkpoint hand-off, bounded attempts, kill switch |
| K | Coordinator dry run selects Task 14 | correct | `cli plan`: Task 14 "Manual clip marking", writer `codex_cloud`, reviewer `claude_subscription`/sonnet-5, `autonomy_enabled: false`, nothing dispatched |
| L | `AUTONOMY_ENABLED` | false | repository variable `AUTONOMY_ENABLED=false`; `ops/policy.json` `autonomy.enabled: false`, `allow_phase_d_and_later: false` |
| M | Unresolved release-blocking findings | none | see "Review history" below |
| N | Actions permissions audit | green | see "Workflow security" below |

## Workflow security

Audited statically across every workflow, since the review job cannot execute
before the orchestrator exists on `main` (see "Bootstrap dependency cycle").

- No `pull_request_target` anywhere. A fork's code is never handed credentials.
- Every AgentOps workflow declares `permissions: {}` at the top level and grants
  the minimum per job. No `write-all`, no `secrets: inherit`.
- Every third-party action is pinned to a full commit SHA.
- No `${{ }}` interpolation inside any AgentOps `run:` block; values reach the
  shell as environment variables. (`ci.yml` interpolates `github.run_id` and
  `github.run_attempt`, which are GitHub-controlled integers.)
- `agentops-review.yml` is split: `choose` runs orchestrator code from the base
  revision with no secrets; `review` holds the credentials and never checks out
  the branch. Without that split an autonomous writer's branch could edit
  `services/agentops` and read the provider secrets out of the runner.
- `agentops-verify.yml` is pinned to the default branch with a guard job.

## Bootstrap dependency cycle

`agentops-review.yml`'s `choose` job runs `services.agentops.cli reviewer` from
the pull request's **base** revision, deliberately: the branch's copy of the
orchestrator is not trusted with secrets. While the orchestrator exists only on
the branch, that job cannot succeed on `main`. The same applies to the
coordinator, worker and watchdog, which `main` does not yet contain.

Requiring those jobs to run green before merge is therefore circular. They are
verified statically before merge and exercised for real immediately after it.

## Review history

Fifteen independent review rounds by Codex Cloud through the GitHub integration,
each against the previous round's head. Findings were repaired in the rounds
they were raised; the repairs and their reasoning are in the commit history and
in the regression tests named after each round.

Defects worth recording because they were structural rather than local:

- Liveness failed open, so a lease could be taken from a worker that was still
  running. Now fails closed, with a bounded escape for a lease whose evidence is
  permanently unanswerable.
- The coordinator would have pushed a task branch's starter commit to `main`,
  after which reconciliation would read the branch as merged and mark the task
  complete before any work existed.
- A worker resuming a branch ran `git checkout -B`, discarding the previous
  worker's commits.
- A `git pull --rebase` retry silently dropped a concurrent writer's state.
  Replaced with re-read plus idempotent re-apply.
- Capability classes carried only a price ceiling, so every class above
  `ROUTINE_CODING` resolved to the same cheap model and the ladder collapsed
  into one rung.

## Review coverage of the frozen commit

The last completed Codex review covered `f50b91c`. Three commits after it were
not reviewed by Codex, because two successive `@codex review` requests went
unanswered — consistent with the subscription's five-hour window being spent
after fifteen rounds in one day. They are recorded here rather than implied:

| Commit | Change | Covering tests |
|---|---|---|
| `c073de0` | The watchdog refreshes the managed STATUS.md block after recovering a stale lease | `test_recovering_a_lease_refreshes_the_human_checkpoint` |
| `29ae6ee` | Capability classes state a preference direction | `TestCapabilityLadder` (3 tests) |
| `556cef1` | The routing audit string reports the rule actually applied | covered by the same class |

## Deferred, non-blocking

Triaged as not release-blocking: none risks security, state integrity, task
correctness, or execution. Follow-up work, not bootstrap work.

1. **Blocked-task checkpoint detail** (`services/agentops/cli.py`, P2, raised
   2026-09-13T17:42Z). When a task exhausts its attempts the managed STATUS.md
   block is refreshed, but it names only the next eligible task; it does not
   name the blocked task, the `BLOCKED_AUTOMATION` reason, or refresh the
   `Updated` timestamp. The halt itself is correct and the activity feed still
   receives a "did not dispatch" entry, so the system stops safely; an operator
   simply has to read the feed or `ops/state/tasks.json` to see why.

2. **`git pull --rebase` in the verify commit step.** Elsewhere this pattern was
   replaced with re-read plus idempotent re-apply, because a rebase between two
   state writers can silently drop the other writer's data. The verify path
   still uses it. It is no longer reachable concurrently — that step is now
   dispatch-only and shares the state-writer concurrency group — so the
   remaining risk is a conflict against a commit landed between checkout and
   push, which fails the run loudly rather than losing data.

## Post-merge smoke test

Run from `main` immediately after the merge of PR #16 (merge commit
`3740cb4`). The merge itself triggered the coordinator, which is the real
proof rather than a simulation of one.

| Claim | Result |
|---|---|
| Coordinator loads from `main` | run 34781468572, success: catalogue refreshed, merged work reconciled, health probed, next task planned |
| Kill switch holds | "Take the task lease", "Hand the task to its lane" and "Commit what the hand-off recorded" all skipped |
| No product code changed | the coordinator's own commit `cbc2a02` touches `ops/state/models.json` and `ops/state/providers.json` only |
| Notification feed works | activity feed entry at 20:40:12Z: "Coordinator did not dispatch — task 14, Manual clip marking, lane codex_cloud" |
| Review workflow loads from `main` | `agentops-review.yml` is present on `main`; its `choose` job is gated to `block-*`/`task-*` branches, so it correctly skipped for this one |

The smoke test also found two defects in `agentops-verify.yml`, both repaired in
a bounded hotfix before autonomy was declared ready:

1. **False lane health on every merge.** `claude-code-action` does not support
   the `push` event and fails with "Unsupported event type: push". The step ran
   under `continue-on-error`, so the outcome was recorded as a failure of the
   Claude subscription lane — a lane that was healthy. A recorded lane failure
   removes that lane from routing.
2. **Two writers racing for `ops/state` on `main`.** A merge fires this workflow
   and the coordinator together, and this workflow's concurrency group was its
   own rather than the shared state-writer group. Its `git pull --rebase` hit a
   conflict in `models.json` and the run died mid-rebase, losing the
   qualification verdicts it had just paid for.

3. **Generated state failed the repository's own formatter.** `ops/state` is
   written by Python in the cloud, and Biome formats floats differently
   (`5.9e-05` against `5.9e-5`). The first catalogue refresh written from `main`
   therefore turned the quality gate red, which would have failed every worker's
   pull request for a reason no worker could fix. Generated state is now
   excluded from the formatter; `cli validate` is what guards those files.

A push-triggered verify run now reports without writing: it proves the control
plane still loads, plans and keeps autonomy off, and records nothing. Only a
deliberate `workflow_dispatch` qualifies models, smoke-tests the Claude lane and
commits verdicts, and it now shares the `agentops-state` concurrency group, so
it can no longer run beside the coordinator or the watchdog.

## Standing invariants

These are enforced in code and must survive later work:

- `AUTONOMY_ENABLED` is the emergency stop and needs no commit to use.
- No ML before the Phase D gate; `allow_phase_d_and_later` is false.
- Frontend implementation routes only to an OpenAI lane. A mixed or frontend
  task is refused by both Claude lanes; `cli plan` shows the refusal.
- Privacy is a filter, not a preference: a lane that does not declare zero data
  retention and deny data collection is ineligible at any price, and a lane
  needing account-level confirmation fails closed until the owner confirms it.
- One writer per task, per branch, per checkout.
