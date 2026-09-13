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


STATUS_BEGIN = "<!-- agentops:progress:begin -->"
STATUS_END = "<!-- agentops:progress:end -->"


def render_status_block(progress: dict[str, Any], next_task: str) -> str:
    """The orchestrator-owned region of STATUS.md.

    AGENTS.md makes STATUS.md the human checkpoint, and every worker brief
    tells the worker to read it. Marking tasks complete only in progress.json
    would leave that file saying work is outstanding after it merged, so a
    worker would start from a false picture of the repository.

    Only the text between the markers is rewritten; everything a human wrote
    around it is left alone.
    """
    done = sorted(state.completed_tasks(progress))
    blocks = sorted(int(b) for b in progress.get("completed_blocks", []))
    return chr(10).join(
        [
            STATUS_BEGIN,
            "",
            "### Autonomous progress",
            "",
            f"- Updated: {progress.get('updated_at', state.now())}",
            f"- Completed tasks: {done}",
            f"- Completed blocks: {blocks}",
            f"- Next eligible task: {next_task}",
            "",
            "Maintained by `services/agentops/reconcile.py`. Edit around this",
            "block, not inside it.",
            "",
            STATUS_END,
        ]
    )


def update_status_file(root: Path, progress: dict[str, Any], next_task: str) -> bool:
    path = root / "STATUS.md"
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    block = render_status_block(progress, next_task)

    if STATUS_BEGIN in text and STATUS_END in text:
        head, rest = text.split(STATUS_BEGIN, 1)
        _, tail = rest.split(STATUS_END, 1)
        updated = head + block + tail
    else:
        # First time: append rather than guessing where a human would want it.
        updated = text.rstrip(chr(10)) + chr(10) * 2 + block + chr(10)

    if updated == text:
        return False
    with path.open("w", encoding="utf-8", newline=chr(10)) as handle:
        handle.write(updated)
    return True


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

    status_updated = False
    if completed:
        state.write_json(ctx.paths.tasks, ctx.tasks)
        state.write_json(ctx.paths.progress, ctx.progress)

        # Keep the human checkpoint honest. A worker told to read STATUS.md
        # would otherwise see merged work still listed as outstanding.
        fresh = coordinator.load_context(root)
        candidate = coordinator.next_eligible(fresh)
        next_task = (
            f"Task {candidate.task.id} - {candidate.task.title}"
            if candidate
            else "none eligible"
        )
        status_updated = update_status_file(root, ctx.progress, next_task)
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
        "status_file_updated": status_updated,
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
