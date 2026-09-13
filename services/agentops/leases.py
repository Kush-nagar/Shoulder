"""Task leases.

One writer per task, per branch, per checkout. Two agents editing the same
checkout is the failure this exists to prevent, so acquisition is exclusive and
a lease is only ever taken from a previous owner once that owner has provably
stopped heartbeating.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from .state import now

ACTIVE_STATES = ("assigned", "implementing", "verifying", "review", "ci", "repairing")
TERMINAL_STATES = ("merged", "abandoned", "blocked")


class LeaseConflict(Exception):
    """Another worker already holds a live lease on this task."""


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def is_stale(lease: dict[str, Any], policy: dict[str, Any]) -> bool:
    """A lease is stale once its owner has missed enough heartbeats.

    Expiry alone is not enough: a worker that is still heartbeating past its
    nominal expiry is alive and must not have its branch taken away.
    """
    settings = policy["lease"]
    beat = int(settings["heartbeat_seconds"])
    allowed = int(settings["stale_after_missed_heartbeats"])
    deadline = timedelta(seconds=beat * allowed)

    last = _parse(lease.get("heartbeat_at")) or _parse(lease.get("acquired_at"))
    if last is None:
        return True
    if datetime.now(UTC) - last > deadline:
        return True

    expires = _parse(lease.get("expires_at"))
    return bool(expires and datetime.now(UTC) > expires + deadline)


def active_leases(
    tasks: dict[str, Any], policy: dict[str, Any]
) -> list[dict[str, Any]]:
    return [
        lease
        for lease in tasks.get("leases", {}).values()
        if lease.get("state") in ACTIVE_STATES and not is_stale(lease, policy)
    ]


def acquire(
    tasks: dict[str, Any],
    policy: dict[str, Any],
    *,
    task_id: int,
    owner: str,
    branch: str,
    assignment: dict[str, Any],
) -> dict[str, Any]:
    """Take an exclusive lease, or raise LeaseConflict."""
    leases = tasks.setdefault("leases", {})
    key = str(task_id)
    existing = leases.get(key)

    if existing and existing.get("state") in ACTIVE_STATES:
        if not is_stale(existing, policy):
            raise LeaseConflict(
                f"task {task_id} is held by {existing.get('owner')} "
                f"(state {existing.get('state')}, "
                f"heartbeat {existing.get('heartbeat_at')})"
            )
        # Recovering a stale lease is a recorded event, not a silent takeover.
        history = existing.setdefault("recovered_from", [])
        history.append(
            {
                "owner": existing.get("owner"),
                "state": existing.get("state"),
                "last_heartbeat": existing.get("heartbeat_at"),
                "recovered_at": now(),
            }
        )

    limit = int(policy["autonomy"]["max_parallel_writers"])
    others = [
        lease
        for lease_key, lease in leases.items()
        if lease_key != key
        and lease.get("state") in ACTIVE_STATES
        and not is_stale(lease, policy)
    ]
    if len(others) >= limit:
        raise LeaseConflict(
            f"max_parallel_writers={limit} already active: "
            f"{sorted(str(o.get('task_id')) for o in others)}"
        )

    duration = int(policy["lease"]["duration_seconds"])
    acquired = datetime.now(UTC)
    lease = dict(existing or {})
    lease.update(
        {
            "task_id": task_id,
            "owner": owner,
            "branch": branch,
            "state": "assigned",
            "assignment": assignment,
            "acquired_at": acquired.isoformat(timespec="seconds"),
            "expires_at": (acquired + timedelta(seconds=duration)).isoformat(
                timespec="seconds"
            ),
            "heartbeat_at": acquired.isoformat(timespec="seconds"),
            "attempts": int(lease.get("attempts", 0)) + 1,
            "checkpoint": lease.get("checkpoint"),
        }
    )
    leases[key] = lease
    return lease


def heartbeat(tasks: dict[str, Any], task_id: int, owner: str) -> dict[str, Any]:
    lease = tasks.get("leases", {}).get(str(task_id))
    if lease is None:
        raise LeaseConflict(f"no lease for task {task_id}")
    if lease.get("owner") != owner:
        raise LeaseConflict(
            f"task {task_id} is held by {lease.get('owner')}, not {owner}"
        )
    lease["heartbeat_at"] = now()
    recorded: dict[str, Any] = lease
    return recorded


def checkpoint(
    tasks: dict[str, Any],
    task_id: int,
    owner: str,
    *,
    state: str,
    commit: str | None = None,
    complete: list[str] | None = None,
    remaining: list[str] | None = None,
    tests: dict[str, Any] | None = None,
    blocker: str | None = None,
    next_action: str | None = None,
) -> dict[str, Any]:
    """Record enough for a fresh worker to continue without the old context."""
    lease = heartbeat(tasks, task_id, owner)
    lease["state"] = state
    lease["checkpoint"] = {
        "at": now(),
        "state": state,
        "commit": commit,
        "complete": complete or [],
        "remaining": remaining or [],
        "tests": tests or {},
        "blocker": blocker,
        "next_action": next_action,
    }
    return lease


def release(tasks: dict[str, Any], task_id: int, state: str) -> dict[str, Any] | None:
    lease = tasks.get("leases", {}).get(str(task_id))
    if lease is None:
        return None
    if state not in TERMINAL_STATES:
        raise ValueError(f"{state} is not a terminal lease state")
    lease["state"] = state
    lease["released_at"] = now()
    released: dict[str, Any] = lease
    return released
