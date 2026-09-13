"""Close the loop after a pull request merges.

Without this the system can dispatch work but never finish it. A worker opens
a pull request, a human or a check merges it, and then nothing marks the task
complete or releases its lease: the next coordinator run sees the same task
still outstanding and still held, and the backlog never advances.

Completion is decided from Git, not from a message. A task is complete when
the branch its lease names has become an ancestor of the merge target, which
is true exactly when the branch has been merged.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from . import coordinator, leases, notify, state


def pull_request_merged(
    branch: str, *, repo: str | None = None, base: str = "main"
) -> bool | None:
    """Whether the pull request for this branch was merged into `base`.

    The base matters. A task branch retargeted to a staging branch and merged
    there has not landed on main, and counting it would mark the task complete
    and release dependent work that is still waiting on code main has not seen.

    Ancestry alone misses the common case: a squash or rebase merge rewrites
    the commits, so the branch tip is not an ancestor of main even though the
    work landed. Without this a task would never be marked complete and the
    coordinator would keep re-dispatching it forever.

    None means the question could not be answered.
    """
    command = [
        "gh",
        "pr",
        "list",
        "--head",
        branch,
        "--base",
        base,
        "--state",
        "merged",
        "--json",
        "number,mergedAt",
        "--limit",
        "1",
    ]
    if repo:
        command += ["--repo", repo]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return None
    try:
        found = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return None
    return bool(found)


def branch_is_merged(root: Path, branch: str, base: str = "origin/main") -> bool:
    """Whether every commit on `branch` is already contained in `base`."""
    for ref in (f"origin/{branch}", branch):
        exists = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "--quiet", ref],
            capture_output=True,
            text=True,
            check=False,
        )
        if exists.returncode != 0:
            continue
        merged = subprocess.run(
            ["git", "-C", str(root), "merge-base", "--is-ancestor", ref, base],
            capture_output=True,
            text=True,
            check=False,
        )
        if merged.returncode == 0:
            return True
    return False


def reconcile(root: Path, *, repo: str | None = None) -> dict[str, Any]:
    """Mark merged tasks complete, release their leases, and record it."""
    ctx = coordinator.load_context(root)
    completed: list[dict[str, Any]] = []

    for key, lease in ctx.tasks.get("leases", {}).items():
        if lease.get("state") in leases.TERMINAL_STATES:
            continue
        branch = lease.get("branch")
        task_id = int(lease.get("task_id", key))
        if not branch:
            continue
        # Either signal is enough: a fast-forward merge shows up as ancestry, a
        # squash or rebase merge only as a merged pull request.
        merged = branch_is_merged(root, str(branch))
        how = "branch is an ancestor of main"
        if not merged and pull_request_merged(str(branch), repo=repo, base="main"):
            merged = True
            how = "pull request was squash or rebase merged into main"
        if not merged:
            continue

        leases.release(ctx.tasks, task_id, "merged")

        done = state.completed_tasks(ctx.progress)
        if task_id not in done:
            done.add(task_id)
            ctx.progress["completed_tasks"] = sorted(done)
            ctx.progress.setdefault("evidence", {})[str(task_id)] = (
                f"merged branch {branch} ({how})"
            )
            ctx.progress["updated_at"] = state.now()

        # A block is complete when every task in it is.
        block = ctx.backlog.block_for_task(task_id)
        if block and set(block.tasks) <= set(state.completed_tasks(ctx.progress)):
            blocks = {int(b) for b in ctx.progress.get("completed_blocks", [])}
            blocks.add(block.id)
            ctx.progress["completed_blocks"] = sorted(blocks)

        completed.append({"task_id": task_id, "branch": branch, "how": how})

    if completed:
        state.write_json(ctx.paths.tasks, ctx.tasks)
        state.write_json(ctx.paths.progress, ctx.progress)
        if repo:
            issue = notify.ensure_feed(ctx.policy, repo=repo)
            for entry in completed:
                if issue is not None:
                    notify.post(
                        issue,
                        "merge",
                        f"Task {entry['task_id']} merged",
                        {"branch": entry["branch"]},
                        repo=repo,
                    )

    return {
        "checked_at": state.now(),
        "completed": completed,
        "completed_tasks": sorted(state.completed_tasks(ctx.progress)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agentops-reconcile")
    parser.add_argument("--root", default=".")
    parser.add_argument("--repo")
    args = parser.parse_args(argv)
    print(json.dumps(reconcile(Path(args.root).resolve(), repo=args.repo), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
