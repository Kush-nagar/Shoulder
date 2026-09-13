"""Hand a task to subscription-backed Codex Cloud.

Codex Cloud is reached through the Codex GitHub integration rather than an API
key: mentioning `@codex <instruction>` on a pull request starts a cloud chat
with that pull request as context, and Codex pushes its work back to the
branch. The work runs in OpenAI's sandbox against the ChatGPT subscription
allowance, so nothing needs an `OPENAI_API_KEY` and nothing needs the owner's
laptop to be awake.

That integration attaches to a pull request, so one has to exist before Codex
can be asked to do anything. This module creates the task branch with an empty
commit, opens the pull request carrying the brief, and posts the mention.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from . import brief as brief_mod
from . import coordinator, notify, state

MENTION = "@codex"


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, cwd=str(cwd) if cwd else None, capture_output=True, text=True, check=False
    )


def _gh(
    args: list[str], *, repo: str | None = None
) -> subprocess.CompletedProcess[str]:
    command = ["gh", *args]
    if repo:
        command += ["--repo", repo]
    return _run(command)


def instruction(task_id: int, title: str) -> str:
    """What Codex is actually told to do.

    Deliberately short. The brief lives in the pull request body and in
    AGENTS.md, and a mention that restates everything buries the instruction.
    """
    return (
        f"{MENTION} Implement canonical Shoulder Task {task_id} — {title}. "
        "The full brief is this pull request's description. Follow AGENTS.md "
        "and CLAUDE.md, stay strictly inside this task's scope, add the tests "
        "the brief names, and run ./scripts/check.ps1 before you finish. "
        "If the task conflicts with a rule in AGENTS.md, stop and say so in a "
        "comment instead of implementing around it."
    )


def ensure_branch(root: Path, branch: str, base: str = "main") -> tuple[bool, str]:
    """Create and push the task branch if it does not exist yet.

    The branch starts from an empty commit: a pull request needs at least one
    commit of difference, and Codex needs a pull request to attach to.
    """
    existing = _run(
        ["git", "-C", str(root), "ls-remote", "--exit-code", "origin", branch]
    )
    if existing.returncode == 0:
        return False, "branch already exists on origin"

    for args in (
        ["git", "-C", str(root), "fetch", "origin", base],
        ["git", "-C", str(root), "checkout", "-B", branch, f"origin/{base}"],
        [
            "git",
            "-C",
            str(root),
            "commit",
            "--allow-empty",
            "-m",
            f"Start {branch}",
        ],
        ["git", "-C", str(root), "push", "-u", "origin", branch],
    ):
        result = _run(args)
        if result.returncode != 0:
            return False, f"{' '.join(args[3:])} failed: {result.stderr.strip()[:200]}"
    return True, "branch created"


def ensure_pull_request(
    root: Path, task_id: int, title: str, branch: str, body: str, *, repo: str | None
) -> tuple[int | None, str]:
    existing = _gh(
        ["pr", "list", "--head", branch, "--state", "open", "--json", "number"],
        repo=repo,
    )
    if existing.returncode == 0:
        found = json.loads(existing.stdout or "[]")
        if found:
            return int(found[0]["number"]), "pull request already open"

    created = _gh(
        [
            "pr",
            "create",
            "--base",
            "main",
            "--head",
            branch,
            "--title",
            f"Task {task_id}: {title}",
            "--body",
            body,
            "--draft",
        ],
        repo=repo,
    )
    if created.returncode != 0:
        return None, f"pr create failed: {created.stderr.strip()[:200]}"
    match = re.search(r"/pull/(\d+)", created.stdout)
    return (int(match.group(1)) if match else None), "pull request opened"


def delegate(
    root: Path, task_id: int, *, repo: str | None = None, dry_run: bool = False
) -> dict[str, Any]:
    """Create the branch and pull request, then hand the task to Codex Cloud."""
    ctx = coordinator.load_context(root)
    task = ctx.backlog.tasks.get(task_id)
    if task is None:
        return {"ok": False, "reason": f"task {task_id} is not canonical"}

    candidate = coordinator.evaluate(ctx, task)
    plan = coordinator.plan(ctx, candidate)
    text = brief_mod.render(root, task_id)
    mention = instruction(task_id, task.title)

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "task": task_id,
            "branch": plan.branch,
            "mention": mention,
            "brief_bytes": len(text),
        }

    created, branch_detail = ensure_branch(root, plan.branch)
    number, pr_detail = ensure_pull_request(
        root, task_id, task.title, plan.branch, text, repo=repo
    )
    if number is None:
        return {"ok": False, "reason": pr_detail, "branch": plan.branch}

    posted = _gh(["pr", "comment", str(number), "--body", mention], repo=repo)
    if posted.returncode != 0:
        return {
            "ok": False,
            "reason": f"could not post the mention: {posted.stderr.strip()[:200]}",
            "pull_request": number,
        }

    if repo:
        issue = notify.ensure_feed(ctx.policy, repo=repo)
        if issue is not None:
            notify.post(
                issue,
                "start",
                f"Task {task_id} delegated to Codex Cloud",
                {
                    "pull request": number,
                    "branch": plan.branch,
                    "billing": "ChatGPT subscription allowance",
                },
                repo=repo,
            )

    return {
        "ok": True,
        "task": task_id,
        "branch": plan.branch,
        "branch_created": created,
        "branch_detail": branch_detail,
        "pull_request": number,
        "pull_request_detail": pr_detail,
        "mechanism": "github-mention",
        "delegated_at": state.now(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agentops-delegate")
    parser.add_argument("--task", type=int, required=True)
    parser.add_argument("--root", default=".")
    parser.add_argument("--repo")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    result = delegate(
        Path(args.root).resolve(), args.task, repo=args.repo, dry_run=args.dry_run
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
