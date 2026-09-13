"""Recovery sweep.

Everything here repairs a failure that event-driven continuation cannot catch
by itself. It is deliberately conservative: it recovers a lease only once the
previous owner has provably stopped heartbeating, and it returns a provider to
service only after its reset time has genuinely passed.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import coordinator, leases, notify, state


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

    # 2. Providers whose cooldown has elapsed. They come back as DEGRADED, so
    #    the next real call is the health check that promotes them.
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
                ctx.providers, lane, "DEGRADED", reason="cooldown window elapsed"
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
        issue = notify.find_issue(ctx.policy["notifications"]["issue_title"], repo=repo)
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
