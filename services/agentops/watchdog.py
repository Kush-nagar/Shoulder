"""Recovery sweep.

Everything here repairs a failure that event-driven continuation cannot catch
by itself. It is deliberately conservative: it recovers a lease only once the
previous owner has provably stopped heartbeating, and it returns a provider to
service only after its reset time has genuinely passed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import coordinator, leases, notify, state

RUNNING_STATUSES = ("queued", "in_progress", "waiting", "requested", "pending")


def owner_finished(lease: dict[str, Any], *, repo: str | None = None) -> bool:
    """Whether the workflow run holding this lease has really stopped.

    Recovering a lease on a timestamp alone would let the sweep take a branch
    away from a worker that is simply slow. When the lease records its run,
    ask GitHub. When it does not, or the query fails, fall back to the
    timestamps -- an unanswerable question should not wedge recovery forever.
    """
    # The worker's own run, when one was recorded. `run_id` is the
    # coordinator's, and that ends in seconds regardless of what the worker is
    # doing, so falling back to it would prove nothing.
    run_id = lease.get("worker_run_id")
    if not run_id:
        if lease.get("pull_request") is not None:
            # Codex Cloud work has no workflow run to inspect. Its liveness is
            # the pull request, and only the timestamps can speak for it.
            return True
        return True
    command = ["gh", "run", "view", str(run_id), "--json", "status"]
    if repo:
        command += ["--repo", repo]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return True
    try:
        status = str(json.loads(result.stdout or "{}").get("status", ""))
    except json.JSONDecodeError:
        return True
    return status not in RUNNING_STATUSES


def sweep(root: Path, *, repo: str | None = None) -> dict[str, Any]:
    ctx = coordinator.load_context(root)
    recovered: list[dict[str, Any]] = []
    returned: list[str] = []

    # 1. Leases whose owner has gone quiet. The lease is marked abandoned rather
    #    than reassigned here: the coordinator decides who takes it next, and it
    #    keeps the checkpoint so the successor does not start over.
    for key, lease in ctx.tasks.get("leases", {}).items():
        if lease.get("state") not in leases.ACTIVE_STATES:
            continue
        if not leases.is_stale(lease, ctx.policy):
            continue
        # Timestamps say the owner looks gone; the run itself says whether it
        # is. Taking a branch from a worker that is still running is the one
        # thing this sweep must never do.
        if not owner_finished(lease, repo=repo):
            continue
        lease["state"] = "abandoned"
        lease["abandoned_at"] = state.now()
        lease["abandoned_reason"] = "no heartbeat within the stale window"
        recovered.append(
            {
                "task_id": lease.get("task_id", key),
                "owner": lease.get("owner"),
                "last_heartbeat": lease.get("heartbeat_at"),
                "checkpoint_kept": bool(lease.get("checkpoint")),
            }
        )

    # 2. Providers whose cooldown has elapsed. A cooldown is exhaustion, not
    #    failure, and the allowance refills on a schedule, so the window
    #    passing is itself the recovery. DEGRADED would keep the lane out of
    #    the pool forever, since nothing else would ever promote it.
    now = datetime.now(UTC)
    for lane, record in ctx.providers.get("lanes", {}).items():
        if record.get("status") != "COOLDOWN":
            continue
        reset = record.get("reset_at")
        if not reset:
            continue
        try:
            elapsed = datetime.fromisoformat(reset) <= now
        except ValueError:
            continue
        if elapsed:
            state.mark_provider(
                ctx.providers, lane, "AVAILABLE", reason="cooldown window elapsed"
            )
            returned.append(lane)

    if recovered:
        state.write_json(ctx.paths.tasks, ctx.tasks)
    if returned:
        state.write_json(ctx.paths.providers, ctx.providers)

    active = leases.active_leases(ctx.tasks, ctx.policy)
    result = {
        "checked_at": state.now(),
        "autonomy_enabled": state.autonomy_enabled(ctx.policy),
        "recovered": recovered,
        "providers_returned": returned,
        "active_leases": len(active),
        # Idle means autonomy is on, nothing is in flight, and work remains.
        # That is the signature of a continuation event that never arrived.
        "idle": bool(
            state.autonomy_enabled(ctx.policy)
            and not active
            and coordinator.next_eligible(ctx) is not None
        ),
    }

    if repo and (recovered or returned):
        issue = notify.ensure_feed(ctx.policy, repo=repo)
        if issue is not None:
            notify.post(
                issue,
                "provider" if returned and not recovered else "blocked",
                "Watchdog recovered orchestrator state",
                {
                    "stale leases": len(recovered),
                    "providers returned": ", ".join(returned) or "none",
                },
                repo=repo,
            )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agentops-watchdog")
    parser.add_argument("--root", default=".")
    parser.add_argument("--repo")
    args = parser.parse_args(argv)
    print(json.dumps(sweep(Path(args.root).resolve(), repo=args.repo), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
