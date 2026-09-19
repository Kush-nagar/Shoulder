"""Build the brief a worker receives.

A worker starts in a fresh context every time. Everything it needs to do the
job correctly has to be in this file: the canonical task, the rules that
override it, the documents it may read, the verification it owes, and any
checkpoint left by a previous attempt.

Keeping the brief narrow is the point. A worker that is told to read the whole
repository will read the whole repository.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import classify, coordinator

HEADER = """# Task brief

You are implementing exactly one canonical Shoulder task. Read this brief, then
the documents it names. Do not explore the rest of the repository.
"""

RULES = """## Rules that override this brief

1. `AGENTS.md` and `CLAUDE.md` win over anything written here. Read both first.
2. A human coach authors every judgment. No model-generated text reaches a player.
3. No scores, rankings, comparisons, or cross-player endpoints.
4. Every table holding team, player, video, judgment, reflection, or event data
   ships with row-level security and isolation tests in this same task.
5. Players never receive coach playback objects or full-match access.
6. No machine learning, inference, embedding, or CV model before the Phase D gate.
7. Buckets stay private; signed URLs stay short-lived and object-specific.
8. Ship the smallest correct thing. No HLS, Redis, Celery, GraphQL, Kubernetes,
   native apps, or microservices without an approved ADR.

If this task conflicts with rules 2 to 5, stop and report the conflict in the
pull request. Do not implement around it.
"""

DISCIPLINE = """## Working rules

- Implement this task now, in this worktree. A plan is not the deliverable and
  neither is a description of what you would do: the branch is read by its
  diff, and a worker that finishes without changing a file has not done the
  task. Plan privately if it helps, then write the code.

- Edit the files yourself, in this turn. Do not hand the implementation to a
  background agent and report that it is running: nothing is watching for it,
  this process is the run, and when it exits the work goes with it. A
  subagent may read or search on your behalf; every write is yours.

- Stay inside this task. Do not redesign adjacent systems or start a later task.
- Public API types come from the FastAPI OpenAPI document. Never hand-write them.
- Any schema change uses Alembic and includes RLS and grants in this task.
- Use these domain words exactly: `observation`, `judgment`, `review_publication`,
  `player_reflection`, `development_goal`, `evidence_clip`.
- Never commit secrets, `.env.remote`, or machine-specific artefacts.
- Never change `ops/policy.json`, `.github/workflows/`, `AGENTS.md`, or
  `CODEOWNERS`. Those decide what this system is allowed to do -- routing,
  budgets, banned providers, the human gates, and the checks themselves. Both
  required checks are automated, so a branch that edited them would be granting
  itself the permission. The merge gate refuses such a branch outright; if the
  task seems to need one, say so in the pull request and stop.
- Never weaken, skip, or mark expected-failure any load-bearing test in `AGENTS.md`.
- Run the named verification below, plus lint and type checks for what you touched.
- Commit at coherent points. If you run out of room, leave the tree working.
"""


FRONTEND_SCOPE = """## What "done" means for the user interface

This task includes interface work, and the interface is in scope: the task is
not complete until a user can actually carry out what it describes against the
real backend. Build it.

Build it to be correct, not decorated. In scope: real data flow, correct
states including loading, empty and error, keyboard operation, focus order,
labels and roles, sensible behaviour at phone width, and the tests this task
names. Out of scope, and deliberately deferred to a later dedicated pass:
visual redesign, brand work, animation, motion, typographic refinement, and
component abstraction nothing yet needs.

Follow `docs/09-frontend-design-system.md` for the tokens and components that
already exist rather than inventing a parallel set. Never invent player-facing
wording: `applied` renders as "You did this.", `opportunity` as "Chance to do
this.", and `not_relevant` is never shown to a player.
"""

REPAIR_HEADER = """# Repair brief

A previous attempt at this task is already on the branch and has opened a pull
request. It did not pass. Your job is to fix what is listed below and nothing
else.

- Do not restart the task or rewrite working code.
- Read the existing diff first (`git log`, `git diff origin/main...HEAD`).
- Treat each finding on its merit. A finding that is wrong, or that asks for
  something this canonical task explicitly excludes, should be answered in the
  pull request rather than implemented -- say why, and leave the code alone.
- Add regression coverage for anything that was genuinely broken.
- Re-run the verification this task owes before you finish.
"""


RESOLVING = """The full thread for each is on the pull request.

**Answer every thread before you finish.** The merge gate counts unresolved
threads, and it cannot tell "already fixed" from "ignored". Changing the lines
a finding points at marks its thread outdated automatically and it stops
counting -- but a fix made anywhere else leaves the thread standing, and the
branch then stays blocked through every remaining repair cycle until the task
is given up on. That is the most likely way this task fails from here.

So: reply saying where you fixed it, or why you are declining it, and then
resolve it. List the open threads and resolve one with:

```
gh api graphql -F o=OWNER -F n=REPO -F p=NUMBER -f query='
  query($o:String!,$n:String!,$p:Int!){ repository(owner:$o,name:$n){
    pullRequest(number:$p){ reviewThreads(first:100){ nodes{
      id isResolved isOutdated
      comments(first:1){ nodes{ path line body } } } } } } }'

gh api graphql -F t=THREAD_ID -f query='
  mutation($t:ID!){ resolveReviewThread(input:{threadId:$t}){
    thread{ isResolved } } }'
```

Resolve only what you actually answered. Resolving a finding you did not
address hides a real defect from the one gate that would have caught it."""


def _repair_section(reason: str, findings_path: Path | None) -> str:
    """What failed, in the smallest form a repairer can act on."""
    lines = ["## What failed"]
    if reason == "ci":
        lines.append(
            "A required check failed on the pull request. Read the failing "
            "job's log through `gh run view --log-failed`, find the cause, "
            "and fix it. Do not disable, skip, or weaken the check."
        )
    else:
        lines.append("Independent review left unresolved findings on the pull request.")

    if findings_path and findings_path.exists():
        try:
            payload = json.loads(findings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            payload = {}
        found = payload.get("findings") or []
        if found:
            lines.append("")
            lines.append("### Review findings")
            for item in found:
                where = item.get("path") or "unknown file"
                line_no = item.get("line")
                at = f"{where}:{line_no}" if line_no else where
                lines.append(f"- `{at}` -- {item.get('summary', '').strip()}")
    if reason == "review":
        # Unconditional, not only when the findings file parsed. A review
        # repair means threads exist by definition; if fetching them failed,
        # the writer needs this more, not less.
        lines.append(RESOLVING)
    lines.append("")
    return "\n\n".join(lines)


def render(
    root: Path,
    task_id: int,
    *,
    repair: str | None = None,
    findings: Path | None = None,
) -> str:
    ctx = coordinator.load_context(root)
    task = ctx.backlog.tasks.get(task_id)
    if task is None:
        raise SystemExit(f"Task {task_id} is not in docs/06-tasks.md")

    candidate = coordinator.evaluate(ctx, task)
    built = coordinator.plan(ctx, candidate)
    result = classify.classify(task)
    block = ctx.backlog.block_for_task(task_id)

    lines: list[str] = [REPAIR_HEADER if repair else HEADER]
    if repair:
        lines.append(_repair_section(repair, findings))
    lines.append(f"## Task {task.id} — {task.title}\n")
    lines.append(f"- Phase: {task.phase}")
    if block:
        lines.append(f"- Block: {block.slug} ({block.name})")
    lines.append(f"- Prerequisites: {list(task.prerequisites) or 'none'}")
    lines.append(f"- Classification: {result.category} / {result.complexity}")
    lines.append(f"- Branch: {built.branch}\n")

    lines.append("### What the canonical task says\n")
    lines.append(task.body.strip() + "\n")

    lines.append("### Documents you may read\n")
    named = ["AGENTS.md", "CLAUDE.md", "STATUS.md", *task.read]
    if block:
        named.append(f"docs/projects/README.md ({block.slug} section)")
    for doc in named:
        lines.append(f"- `{doc}`")
    lines.append("\nRead nothing else unless a failing check points you at it.\n")

    lines.append("### Verification you owe\n")
    lines.append(f"{task.test}\n")
    lines.append(f"Definition of done: {task.done}\n")
    lines.append(
        "Run `./scripts/check.ps1` before you finish. Report the real result; "
        "never describe a check you did not run.\n"
    )

    if result.context7_expected:
        lines.append(
            "### External documentation\n\n"
            "This task touches third-party APIs whose current behaviour matters. "
            "Consult current official documentation for them rather than relying "
            "on recalled syntax. Do not use it for this repository's own logic.\n"
        )

    if result.security_risk or result.migration_risk or result.destructive_risk:
        flags = [
            name
            for name, on in (
                ("security and privacy", result.security_risk),
                ("schema migration", result.migration_risk),
                ("destructive or retention behaviour", result.destructive_risk),
            )
            if on
        ]
        lines.append(
            "### Elevated risk\n\n"
            f"This task carries: {', '.join(flags)}. Work conservatively, prefer "
            "the explicit implementation over the clever one, and add the "
            "isolation tests in this same task.\n"
        )

    lease = ctx.tasks.get("leases", {}).get(str(task_id))
    checkpoint = (lease or {}).get("checkpoint")
    if checkpoint:
        lines.append("### Checkpoint from a previous attempt\n")
        lines.append(f"- Last state: {checkpoint.get('state')}")
        lines.append(f"- Last commit: {checkpoint.get('commit')}")
        lines.append(
            f"- Already complete: {checkpoint.get('complete') or 'nothing recorded'}"
        )
        lines.append(f"- Remaining: {checkpoint.get('remaining') or 'not recorded'}")
        if checkpoint.get("blocker"):
            lines.append(f"- Known blocker: {checkpoint['blocker']}")
        if checkpoint.get("next_action"):
            lines.append(f"- Intended next action: {checkpoint['next_action']}")
        lines.append(
            "\nVerify this against `git log` and the working tree before trusting "
            "it, then continue from there rather than starting over.\n"
        )

    if result.category in ("frontend", "mixed"):
        lines.append(FRONTEND_SCOPE)

    lines.append(RULES)
    lines.append(DISCIPLINE)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agentops-brief")
    parser.add_argument("--task", type=int, required=True)
    parser.add_argument("--root", default=".")
    parser.add_argument("--out")
    parser.add_argument(
        "--repair",
        choices=("ci", "review"),
        help="write a repair brief for an existing branch instead of a fresh one",
    )
    parser.add_argument(
        "--findings", help="path to a saved review verdict, for a review repair"
    )
    args = parser.parse_args(argv)

    text = render(
        Path(args.root).resolve(),
        args.task,
        repair=args.repair,
        findings=Path(args.findings) if args.findings else None,
    )
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
