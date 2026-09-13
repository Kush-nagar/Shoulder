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

- Stay inside this task. Do not redesign adjacent systems or start a later task.
- Public API types come from the FastAPI OpenAPI document. Never hand-write them.
- Any schema change uses Alembic and includes RLS and grants in this task.
- Use these domain words exactly: `observation`, `judgment`, `review_publication`,
  `player_reflection`, `development_goal`, `evidence_clip`.
- Never commit secrets, `.env.remote`, or machine-specific artefacts.
- Never weaken, skip, or mark expected-failure any load-bearing test in `AGENTS.md`.
- Run the named verification below, plus lint and type checks for what you touched.
- Commit at coherent points. If you run out of room, leave the tree working.
"""


def render(root: Path, task_id: int) -> str:
    ctx = coordinator.load_context(root)
    task = ctx.backlog.tasks.get(task_id)
    if task is None:
        raise SystemExit(f"Task {task_id} is not in docs/06-tasks.md")

    candidate = coordinator.evaluate(ctx, task)
    built = coordinator.plan(ctx, candidate)
    result = classify.classify(task)
    block = ctx.backlog.block_for_task(task_id)

    lines: list[str] = [HEADER]
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

    lines.append(RULES)
    lines.append(DISCIPLINE)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agentops-brief")
    parser.add_argument("--task", type=int, required=True)
    parser.add_argument("--root", default=".")
    parser.add_argument("--out")
    args = parser.parse_args(argv)

    text = render(Path(args.root).resolve(), args.task)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
