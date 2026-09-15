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


# How far past expiry a lease may sit before an unanswerable liveness question
# stops protecting it. Long enough that an API outage cannot cause a takeover,
# short enough that a lease pointing at a deleted run does not wedge forever.
UNRESOLVED_GRACE_MULTIPLE = 8
# A lease whose evidence is a pull request waits far longer before an
# unanswerable query releases it. Eight grace windows is two hours, and a Codex
# Cloud task or a pull request awaiting review can legitimately be open for
# much longer than that; releasing it would put a second writer on the branch.
UNRESOLVED_PULL_REQUEST_MULTIPLE = 96


def owner_finished(
    lease: dict[str, Any],
    *,
    repo: str | None = None,
    policy: dict[str, Any] | None = None,
) -> bool:
    """Whether whatever holds this lease has really stopped.

    Fails closed. If the question cannot be answered -- an API outage, a rate
    limit, a bad token -- this reports "still running", because reclaiming a
    lease whose worker is alive puts a second writer on its branch, and that is
    worse than recovery being late.

    The exception is a lease that has been unanswerable for a long time, which
    would otherwise wedge forever; see UNRESOLVED_GRACE_MULTIPLE.
    """
    # The worker's own run, when one was recorded. `run_id` is the
    # coordinator's, and that ends in seconds regardless of what the worker is
    # doing, so falling back to it would prove nothing.
    run_id = lease.get("worker_run_id")
    pull_request = lease.get("pull_request")

    if run_id is None and pull_request is None:
        # Nothing was ever attached, so nothing could still be running on this
        # lease's behalf.
        return True

    # Every attached signal gets a say, and any one of them saying "still
    # active" wins. A worker's run finishing does not mean the work is done
    # when its pull request is still open and under review.
    answers: list[bool | None] = []
    if run_id:
        answers.append(_run_finished(str(run_id), repo=repo))
    if pull_request is not None:
        answers.append(_pull_request_finished(int(pull_request), repo=repo))

    if any(answer is False for answer in answers):
        return False
    if all(answer is True for answer in answers):
        return True

    # At least one signal was unanswerable.
    if pull_request is not None:
        # Never release a pull-request lease on a timer. The pull request still
        # exists and can be asked about again later, so releasing it means
        # guessing that work stopped -- and guessing wrong puts a second writer
        # on the branch. A lease stuck here is surfaced instead; see
        # unresolved_too_long, which the sweep reports rather than acts on.
        return False
    return _long_unresolved(lease, policy)


def unresolved_too_long(lease: dict[str, Any], policy: dict[str, Any] | None) -> bool:
    """Whether a held-but-unanswerable lease has been stuck long enough to
    deserve a human's attention.

    This is reported, never acted on. Releasing a lease because a query keeps
    failing is guessing that the work stopped, and guessing wrong puts a second
    writer on the branch.
    """
    return _long_unresolved(lease, policy, UNRESOLVED_PULL_REQUEST_MULTIPLE)


def _long_unresolved(
    lease: dict[str, Any],
    policy: dict[str, Any] | None,
    multiple: int = UNRESOLVED_GRACE_MULTIPLE,
) -> bool:
    if policy is None:
        return False
    settings = policy["lease"]
    window = (
        int(settings["heartbeat_seconds"])
        * int(settings["stale_after_missed_heartbeats"])
        * multiple
    )
    last = lease.get("heartbeat_at") or lease.get("acquired_at")
    if not last:
        return True
    try:
        seen = datetime.fromisoformat(str(last))
    except ValueError:
        return True
    return (datetime.now(UTC) - seen).total_seconds() > window


def _run_finished(run_id: str, *, repo: str | None = None) -> bool | None:
    """True finished, False running, None unanswerable."""
    command = ["gh", "run", "view", run_id, "--json", "status"]
    if repo:
        command += ["--repo", repo]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        return None
    try:
        status = str(json.loads(result.stdout or "{}").get("status", ""))
    except json.JSONDecodeError:
        return None
    return status not in RUNNING_STATUSES


def _pull_request_finished(number: int, *, repo: str | None = None) -> bool | None:
    """True finished, False still open, None unanswerable."""
    command = ["gh", "pr", "view", str(number), "--json", "state"]
    if repo:
        command += ["--repo", repo]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return None
    return str(payload.get("state", "")).upper() != "OPEN"


def branch_pull_request_open(branch: str, *, repo: str | None = None) -> bool | None:
    """Whether any open pull request is on this branch.

    True open, False none, None unanswerable. It lives here beside the other
    liveness queries because it answers the same question they do -- is there
    still something in play on this branch -- and its callers fail closed on
    None for the same reason.

    The branch is asked about rather than a number because the case this
    exists for is precisely the one where no number was captured.
    """
    command = [
        "gh",
        "pr",
        "list",
        "--head",
        branch,
        "--state",
        "open",
        "--json",
        "number",
    ]
    if repo:
        command += ["--repo", repo]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        return None
    if not (result.stdout or "").strip():
        # A zero exit with nothing on stdout is not an answer. Reading it as
        # "no pull request" would free a lease on a truncated response, which
        # is exactly what the fail-closed contract above forbids.
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, list):
        # `--json number` returns an array. Anything else means the command
        # answered a different question than the one that was asked.
        return None
    return bool(payload)


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
        if not owner_finished(lease, repo=repo, policy=ctx.policy):
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
        # STATUS.md is not written here any more: it is on the protected
        # default branch and nothing in normal operation pushes there. The
        # Control Center carries the live picture instead.
    if returned:
        state.write_json(ctx.paths.providers, ctx.providers)

    stuck = [
        {
            "task_id": lease.get("task_id", key),
            "pull_request": lease.get("pull_request"),
            "last_heartbeat": lease.get("heartbeat_at"),
        }
        for key, lease in ctx.tasks.get("leases", {}).items()
        if lease.get("state") in leases.ACTIVE_STATES
        and leases.is_stale(lease, ctx.policy)
        and unresolved_too_long(lease, ctx.policy)
    ]

    active = leases.active_leases(ctx.tasks, ctx.policy)
    result = {
        "checked_at": state.now(),
        "stuck_unresolved": stuck,
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
