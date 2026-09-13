"""Task leases.

One writer per task, per branch, per checkout. Two agents editing the same
checkout is the failure this exists to prevent, so acquisition is exclusive and
a lease is only ever taken from a previous owner once that owner has provably
stopped heartbeating.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from .state import now

ACTIVE_STATES = ("assigned", "implementing", "verifying", "review", "ci", "repairing")
TERMINAL_STATES = ("merged", "abandoned", "blocked")


class LeaseConflict(Exception):
    """Another worker already holds a live lease on this task."""


class AttemptsExhausted(Exception):
    """This task has used its implementation attempts and must be escalated."""


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def is_stale(lease: dict[str, Any], policy: dict[str, Any]) -> bool:
    """Whether a lease may be taken from its owner.

    A worker cannot heartbeat while a harness is running: the implementation
    step is one Actions step that can last the whole job. Treating a missed
    heartbeat alone as death would abandon a live 90-minute worker after 15
    minutes and let a second writer onto its branch, which is the exact
    failure the lease exists to prevent.

    So a lease is stale only once BOTH are true: its nominal expiry, which
    matches the worker job timeout, has passed, and nothing has heartbeated
    since. The watchdog additionally proves the owner is really gone by
    checking its workflow run before reclaiming; see watchdog.owner_finished.
    """
    settings = policy["lease"]
    beat = int(settings["heartbeat_seconds"])
    allowed = int(settings["stale_after_missed_heartbeats"])
    grace = timedelta(seconds=beat * allowed)
    now_utc = datetime.now(UTC)

    last = _parse(lease.get("heartbeat_at")) or _parse(lease.get("acquired_at"))
    if last is None:
        return True

    expires = _parse(lease.get("expires_at"))
    if expires is None:
        return now_utc - last > grace
    return now_utc > expires + grace and now_utc - last > grace


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
    run_id: str | None = None,
    owner_finished: Callable[[dict[str, Any]], bool] | None = None,
) -> dict[str, Any]:
    """Take an exclusive lease, or raise LeaseConflict.

    `owner_finished` proves the previous holder really stopped. Timestamps
    alone are not proof: a worker queued longer than the grace window looks
    stale while being entirely alive, and reassigning it puts a second writer
    on its branch. Callers that can ask the platform should pass this.
    """
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
        if owner_finished is not None and not owner_finished(existing):
            raise LeaseConflict(
                f"task {task_id} looks stale but its owner "
                f"{existing.get('owner')} is still running"
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

    attempts = int((existing or {}).get("attempts", 0))
    max_attempts = int(policy["escalation"]["max_implementation_attempts"])
    if attempts >= max_attempts:
        raise AttemptsExhausted(
            f"task {task_id} has used {attempts} of {max_attempts} attempts"
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
            "run_id": run_id,
            "checkpoint": lease.get("checkpoint"),
        }
    )
    leases[key] = lease
    return lease


def attach_worker(
    tasks: dict[str, Any],
    task_id: int,
    *,
    run_id: str | None = None,
    run_attempt: str | None = None,
    pull_request: int | None = None,
) -> dict[str, Any]:
    """Record what is really doing the work, once it exists.

    The lease is taken by the coordinator, whose own run ends in seconds. If
    the watchdog checks that run it proves nothing about the worker, and can
    abandon a live worker's branch. The worker -- or, for Codex Cloud, the
    pull request Codex is attached to -- is recorded here instead.
    """
    lease = tasks.get("leases", {}).get(str(task_id))
    if lease is None:
        raise LeaseConflict(f"no lease for task {task_id}")
    if run_id:
        # The bare id, because that is what `gh run view` takes. The attempt is
        # recorded beside it rather than folded in: GitHub keeps the id across
        # a re-run, so the attempt is what tells two runs apart.
        lease["worker_run_id"] = run_id
    if run_attempt:
        lease["worker_run_attempt"] = str(run_attempt)
    if pull_request is not None:
        lease["pull_request"] = pull_request
    lease["heartbeat_at"] = now()
    attached: dict[str, Any] = lease
    return attached


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
