# AgentOps three-writer verification

Evidence index for the local Codex lane and concurrent execution, delivered on
branch `agentops/verdict-sees-clean-review`. Operation:
[`ops/README.md`](../ops/README.md).

This record exists so the claim "three writable workers are safe" can be
checked rather than trusted. Every row names what was run and where the result
lives.

Commits `d5fd09a` (lane and concurrency), `47bcf7c` (review fixes), `5e3e88b`
(JSON formatting), `92703bf` (lane qualification), `397b906` (failover fixtures
and two smoke-found defects).

Baseline before this work: 910 AgentOps tests, 909 passing, 1 skipped. After:
1334 in the repository suite, 289 skipped for want of a local database or
object store; AgentOps' own share rose from 910 to 976.

## What was asked for, and where it is

| # | Requirement | Result | Evidence |
|---|---|---|---|
| 1 | Local Codex CLI as a first-class executor | done | `executors.CodexCliExecutor`; `for_lane("codex_local")`; `availability()` reports it beside the other two |
| 2 | Codex takes frontend, architecture, security/RLS, migrations, hard review | done | `ops/policy.json` `capability_classes.*.prefer_lanes`; row G below |
| 3 | Claude stays coordinator and ordinary backend writer | done | `ROUTINE_CODING.prefer_lanes` is Claude first; row G |
| 4 | DeepSeek takes overflow, mechanical and test work | done | `CHEAP_MECHANICAL.prefer_lanes` is OpenRouter first; row G |
| 5 | Shared state and events safe under concurrency | done | rows B, C, D |
| 6 | Dependency-aware parallel scheduling | done | rows E, H |
| 7 | Every writable worker isolated in its own branch and worktree | done | rows F, I |
| 8 | At most three writable product tasks at once | done | `autonomy.max_parallel_writers: 3`; rows E, I |
| 9 | Exhausted or unavailable provider reaches another authorised lane | done | row J |
| 10 | Dashboard shows provider, model, effort, task, branch, heartbeat, status, retries | done | row K |

## Gates

| # | Gate | Result | Evidence |
|---|---|---|---|
| A | Full Shoulder quality gate | green | `scripts/check.ps1` end to end, exit 0: Biome format + lint + typecheck, node tests, ruff format, ruff check, mypy (85 files), 1334 unittest, OpenAPI contract drift, production build, auth-bundle test, Playwright smoke on Chromium, Firefox and WebKit, `git diff --check` |
| B | Concurrent state writes lose nothing | proven | `test_agentops_parallel.TestConcurrentStateWrites`: three **separate OS processes** write 40 records each; all 120 survive and the ledger is still valid JSON. Threads were deliberately not used — they would pass on the GIL alone while the lock did nothing |
| C | Concurrent event writes lose nothing and tear nothing | proven | `TestConcurrentEventWrites`: three processes, 60 events each; every one of the 180 lines parses and each writer's sequence is complete |
| D | The lock behaves under failure | proven | `TestTheLockItself`: a second holder is excluded; a holder killed mid-write (`os._exit`) releases it, so a killed worker cannot wedge the ledger; re-entering it in one thread fails immediately rather than waiting for itself |
| E | Two and three writers, and a fourth refused | proven | `TestTheWriterCap`: two hold leases, three hold leases, the fourth raises `LeaseConflict` naming `max_parallel_writers=3` |
| F | Worktree isolation | proven | `TestWorktreeIsolation`: three branches resolve to three directories, none of them the coordinator's checkout |
| G | The routing table, as behaviour | proven | `TestTheRoutingPolicyItWasAskedFor`: frontend → Codex; security → Codex at `xhigh`; migrations → Codex at `xhigh`; ordinary backend → Claude; mechanical → DeepSeek at `low`; reviewer never the writer's family |
| H | Dependency blocking | proven | `TestDependencyBlocking`: a task with an unmet prerequisite is never eligible; a leased task is never offered twice; free slots never exceed what is startable, which is what stops the loop spinning |
| I | **Three real writers at once** | proven | Controlled smoke, 2026-09-19: three `codex exec` processes, three git worktrees, three branches, one shared `.agentops/local`. All three completed (14.6s, 13.2s, 14.6s) and wrote the file each was asked for; afterwards all three leases, all three worker records and all six events were intact |
| J | Exhaustion reaches another authorised lane | proven | `test_claude_exhaustion_routes_eligible_work_to_deepseek`; `test_repeated_failure_escalates_to_codex`. Against the real backlog: Task 16 dead-ended on 2026-09-17 with `BLOCKED_PROVIDER: no authorised lane can implement a mixed/EXTREME task`; the same classification now routes to `codex_local` at `xhigh` |
| K | Dashboard fields | present | `dashboard.snapshot` per worker: provider, model, **effort**, capability class, lane, harness, branch, worktree, phase, elapsed, **heartbeat**, lease state, **attempts**, verification, review, escalations, failures |
| L | Restart and resume find parallel work | proven | `TestResumeFindsParallelWork`: every waiting task is found, not just the first; each names its own branch and worktree; merged, unready and vanished-worktree cases are excluded; recovery works with no coordinator breadcrumb written at all |
| M | Codex result parsing | proven | `TestCodexResultParsing`, against JSONL recorded from codex-cli 0.154.0: a completed turn succeeds, a failed turn fails on the stream as well as the exit code, usage is captured, an exhausted allowance is told apart from a defect, and a failing test that merely prints "usage limit" is still a defect |
| N | Existing regression suite | green | 1334 tests, 289 skipped, 0 failures |

## The lock, and why the tests for it are trustworthy

`localstate.write` was already atomic, which is enough for one writer. Every
ledger is updated by reading it, changing one key and writing it back, and two
processes doing that concurrently both read the same version — so the second
write discards the first. With one writer that could not happen; with three it
is a matter of timing, and the lost record would be a lease, which is two
writers on one branch.

The tests were checked against a disabled lock before being trusted. With
`localstate.lock` neutered to a no-op, six of them fail — records lost, ledger
corrupted, event lines lost, no exclusion, lost updates between threads,
breadcrumbs overwritten. A concurrency test that passes either way proves
nothing, so this was established rather than assumed.

## Defects this work found

Nine, all fixed here. Three came from an independent Codex review of `d5fd09a`
run through the new lane, two from running three writers for real, and two more
from running the review gate itself against a real pull request.

| Found by | Defect |
|---|---|
| Codex review | `save_leases` wrote each worker's whole in-memory snapshot back over the ledger, deleting any lease acquired since it started |
| Codex review | `project.save` shared a file with the in-flight breadcrumbs while ignoring their lock, so the lock protected nothing |
| Codex review | Resume depended on a note the coordinator wrote after a worker had already finished, so a coordinator killed in that gap stranded a finished branch with a held lease |
| Parallel smoke | The stdin prompt file was unlinked before the child exited; Windows refuses to delete a file another process holds open, so the run died over a temporary file |
| Parallel smoke | The ledger lock is not reentrant, so a caller that took it and then called a locking helper waited 30s for itself and then blamed another worker |
| Running the gate | **The review gate could accept a self-review.** Choosing an independent reviewer means excluding the writer's family, and the lease recording the writer lives in ignored local state the workflow cannot see -- so it recomputed the writer from current routing. On Task 15 that guess said Codex had written a branch Claude wrote, judged Anthropic independent, and nominated Claude to review its own work |
| Running the gate | The job that chooses the reviewer held only `contents: read`, so it could not read the writer marker it now depends on, and refused with a bare exit code -- its answer goes to a redirected file and `set -e` aborted the step before anything printed the reason |

Two further latent defects were fixed on the way: argv[0] was spawned
unresolved, and Windows `CreateProcess` only appends `.exe`, so the npm `.CMD`
shims for `codex` and `opencode` failed to start while availability reported
them installed; and review prompts embed up to 60000 characters of diff against
a 32767-character Windows command line, so every review on this platform died
before the harness started. Codex now takes its prompt on stdin. The other two
lanes still use argv and say so — moving them wants its own verification
against their CLIs.

## How the reviewer is kept independent

The writer is established, never guessed. A pull request records the lane that
wrote it as a marker in its body, so the answer travels with the branch; the
reviewer command reads the lease first, that marker second, and **refuses**
when it has neither. An unknown writer means no reviewer can be shown to be
independent of it, and a guess is what produced the self-review above.

It also declines lanes the caller cannot start. `codex_local` runs `codex exec`
against a subscription no Actions runner has and has no step in the review
workflow, so choosing it there would report success having reviewed nothing and
leave the verdict waiting for a review that could never arrive. Asked only for
lanes it can run, CI picks DeepSeek to review Claude's work and Claude to review
Codex's.

A pull request opened before this existed carries no marker, so it refuses until
one is added -- which is the fail-closed direction, and is what happened to PR
#32. Its marker was set from the lease, which records Claude as the writer.

## What this does not establish

- **Three product tasks have never run in parallel**, because the canonical
  backlog cannot offer three at once: Tasks 15 to 22 form a strict chain, each
  waiting on the one before. The scheduler tops up by how many tasks are
  actually startable, so it correctly runs one writer here. Row I is the
  capability; the backlog is the limit.
- **Claude writes none of the remaining roadmap.** Tasks 15 to 22 are either
  frontend or carry a security, destructive or migration risk, so every one of
  them routes to Codex. That is the routing that was asked for, but it puts the
  whole remainder on one subscription window.
- **Tasks 23 and later cannot start.** `ops/policy.json` `gates.real_use_gate`
  is false and only a human sets it, because it attests to real coach and
  player use. The autonomous ceiling is Task 22.
- **The Codex GitHub connector is not connected.** Every `@codex` request on PR
  #32 was answered with "create a Codex account and connect to github", so the
  `codex_cloud` lane cannot review anything despite its recorded 2026-09-13
  qualification. Nothing depends on it: the reviewer selection above routes
  around it. Reconnecting it is only needed to get Codex Cloud reviews
  specifically.
- **The OpenRouter review path had never executed before this.** Earlier runs
  that reported a successful review had only posted an `@codex` comment. Its
  endpoint was checked directly instead: `https://openrouter.ai/api` plus the
  SDK's `/v1/messages` answers 200 with the qualified DeepSeek model.
