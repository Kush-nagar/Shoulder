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


class RepairBudgetExhausted(Exception):
    """This task has used its repair cycles for that kind of failure."""


REPAIR_COUNTERS = {"ci": "ci_repair_cycles", "review": "review_repair_cycles"}


def begin_repair(
    tasks: dict[str, Any],
    policy: dict[str, Any],
    task_id: int,
    *,
    reason: str,
    once_key: str | None = None,
) -> dict[str, Any]:
    """Hand a task back to a writer to fix a failing check or a review finding.

    Deliberately not a fresh `acquire`. A repair is the same attempt continuing
    on the same branch, so counting it as a new implementation attempt would
    burn the task's attempt budget on ordinary engineering failures and block
    work that was one lint fix from done. The two repair ceilings are separate
    from that budget and from each other, so a branch that keeps failing CI
    cannot also exhaust its review allowance.

    Clearing the attached run matters: the lease belongs to whichever run is
    doing the work, and the worker refuses to start against a lease held by a
    different run. Leaving the finished run attached would refuse every repair.

    Incrementing a counter is not idempotent, and the caller writes this to a
    branch other writers push to, so a losing race makes it re-read and
    re-apply. `once_key` -- the triggering run -- makes the second application
    a no-op, exactly as `record_spend` does for the same reason. Without it a
    contended push would spend two repair cycles for one failure.
    """
    if reason not in REPAIR_COUNTERS:
        raise ValueError(f"{reason} is not a repairable failure kind")
    lease = tasks.get("leases", {}).get(str(task_id))
    if lease is None:
        raise LeaseConflict(f"no lease for task {task_id}")
    if once_key is not None and once_key in (lease.get("repairs_applied") or {}):
        already: dict[str, Any] = lease
        return already
    if lease.get("state") in TERMINAL_STATES:
        raise LeaseConflict(
            f"task {task_id} lease is {lease.get('state')}; nothing to repair"
        )

    counter = REPAIR_COUNTERS[reason]
    ceiling = int(policy["escalation"][f"max_{counter}"])
    used = int(lease.get(counter, 0))
    if used >= ceiling:
        raise RepairBudgetExhausted(
            f"task {task_id} has used {used} of {ceiling} {reason} repair cycles"
        )

    lease[counter] = used + 1
    # A repair is a fresh worker job, so it gets a fresh window. Leaving the
    # original expiry in place would let the watchdog reclaim the branch part
    # way through the fix.
    started = datetime.now(UTC)
    lease["expires_at"] = (
        started + timedelta(seconds=int(policy["lease"]["duration_seconds"]))
    ).isoformat(timespec="seconds")
    lease["state"] = "repairing"
    lease["repair_reason"] = reason
    lease["heartbeat_at"] = now()
    if once_key is not None:
        lease.setdefault("repairs_applied", {})[once_key] = {
            "reason": reason,
            "at": now(),
        }
    lease.pop("worker_run_id", None)
    lease.pop("worker_run_attempt", None)
    repaired: dict[str, Any] = lease
    return repaired


FAILURE_CLASSES = {
    # The harness or the model provider fell over. The lane is separately
    # marked DEGRADED, so the coordinator's next attempt takes the fallback
    # chain instead of the lane that just failed.
    "provider": "the provider harness failed before a pull request existed",
    # The worker itself ended without producing one: a bad brief, a failed
    # install, a cancelled job. Nothing here blames a lane.
    "worker": "the worker finished without opening a pull request",
}


def abandon_finished_worker(
    tasks: dict[str, Any],
    task_id: int,
    *,
    run_id: str,
    branch: str,
    failure_class: str,
    pull_request_open: bool,
) -> dict[str, Any]:
    """Free a lease whose worker is provably over and left no pull request.

    Without this the loop stops dead. The lease stays `assigned` and the
    watchdog cannot touch it until `expires_at` -- the worker's full 90-minute
    job timeout -- has passed, even though the run died in under a minute and
    `owner_finished` would already answer "yes". That is an hour and a half of
    nothing, for a failure the system knew about immediately.

    The caller is the finalize job, which runs only after the work job has
    reached a conclusion. That job dependency is the liveness proof; no
    timestamp or API answer is trusted in its place. Every other condition is
    checked here and refuses rather than guesses, because the one outcome worse
    than a late recovery is a second writer on a live worker's branch:

    * the lease must still be active -- a terminal one is already resolved, and
      this makes the whole transition idempotent across the caller's retries;
    * `run_id` must be the run recorded on the lease, so a re-run, or a
      finalize job that lost a race and is reporting late, cannot abandon the
      lease a newer worker now holds;
    * `branch` must be the leased branch, so a misdispatched run cannot free
      another task's lease;
    * no pull request may exist, attached or open. `pull_request_open` is
      supplied by the caller and must fail closed: an unanswerable query means
      "a pull request may exist", which leaves the lease alone and lets the
      normal stale path handle it.

    Attempts and the checkpoint are deliberately left as they are. `acquire`
    reads both off the existing record, so the next attempt counts against the
    same budget and starts from whatever progress was saved, rather than
    beginning again with a fresh allowance.
    """
    if failure_class not in FAILURE_CLASSES:
        raise ValueError(f"{failure_class} is not a worker failure class")
    lease = tasks.get("leases", {}).get(str(task_id))
    if lease is None:
        raise LeaseConflict(f"no lease for task {task_id}")
    if lease.get("state") not in ACTIVE_STATES:
        raise LeaseConflict(
            f"task {task_id} lease is {lease.get('state')}; nothing to recover"
        )
    if str(lease.get("worker_run_id") or "") != str(run_id):
        raise LeaseConflict(
            f"task {task_id} is attached to worker run "
            f"{lease.get('worker_run_id')}, not {run_id}"
        )
    if str(lease.get("branch") or "") != str(branch):
        raise LeaseConflict(
            f"task {task_id} is leased on {lease.get('branch')}, not {branch}"
        )
    if lease.get("pull_request") is not None or pull_request_open:
        raise LeaseConflict(
            f"task {task_id} has a pull request; the branch is still in play"
        )

    lease["state"] = "abandoned"
    lease["abandoned_at"] = now()
    lease["abandoned_reason"] = FAILURE_CLASSES[failure_class]
    # Kept separate from the prose reason so the classification stays readable
    # by something other than a human: a provider failure and a worker failure
    # lead to different next attempts.
    lease["failure_class"] = failure_class
    lease["abandoned_by_run"] = str(run_id)
    recovered: dict[str, Any] = lease
    return recovered


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
