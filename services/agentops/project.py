"""Carry the canonical backlog from the first task to the last.

Everything each step needs already exists. `local.run_once` takes one task from
assignment to `ready_for_pr`; `review.verdict` says whether a pull request is
clear on review grounds; `reconcile.reconcile` marks merged work complete and
releases its lease; `governance.violations` says what a branch may not touch.
What was missing was the part that joins them up, so an operator had to sit
between every stage and type the next command.

That is all this module is: the join. It decides nothing the modules below it
already decide, and it deliberately does not become a second GitHub framework
-- every call it makes to GitHub goes through `gh`, in one place, and the
things that must never happen (a forced merge, a bypassed branch protection, a
discarded local change, a reset, a stash, a dependent task started before its
prerequisite merged) are not implemented at all rather than guarded against.

It stops rather than improvising. Every stop has a name, and the name says
whose problem it is:

  PROJECT_COMPLETE          nothing is left to do
  BLOCKED_LOCAL_CHECKOUT    the coordinator's own checkout has changes nobody
                            has accounted for, so nothing may be pushed
  BLOCKED_WAITING_PROVIDER  every permitted provider is out of allowance; the
                            work is intact and waiting
  BLOCKED_HUMAN             a real engineering decision is needed, with the
                            exact findings that produced it
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from services.agentops import (
    approvals,
    coordinator,
    delegate,
    governance,
    local,
    localstate,
    state,
)
from services.agentops import brief as brief_mod
from services.agentops import reconcile as reconcile_mod
from services.agentops import review as review_mod

RUNNING = "PROJECT_RUNNING"
COMPLETE = "PROJECT_COMPLETE"
BLOCKED_LOCAL_CHECKOUT = "BLOCKED_LOCAL_CHECKOUT"
BLOCKED_WAITING_PROVIDER = "BLOCKED_WAITING_PROVIDER"
BLOCKED_HUMAN = "BLOCKED_HUMAN"

# How long one gate may take before the loop gives the question back to a
# person, and how often it is asked. CI on this repository runs for minutes,
# and a cloud reviewer answers minutes after that, so the ceiling is generous
# and the poll is not: asking every few seconds buys nothing and spends rate
# limit.
DEFAULT_POLL_SECONDS = 30
DEFAULT_GATE_TIMEOUT_SECONDS = 3600

# Paths a task branch must never carry, whatever a worker decided. Runtime
# state and credentials are the two that would actually be catastrophic, and
# both are gitignored already -- this is the second lock on the same door,
# because `git add -A` is one typo in an ignore file away from a leak.
NEVER_COMMIT = re.compile(
    r"(^|/)(\.env($|\..*)|\.agentops/|\.tools/|.*\.pem$|.*\.key$|"
    r"secrets?\.(json|ya?ml|txt)$)",
    re.IGNORECASE,
)

# GitHub's own rollup buckets. "skipping" is not failure and not success; a
# skipped required check cannot block a merge, so it is not waited on.
CI_PENDING = ("pending",)
CI_FAILING = ("fail", "cancel")


class Stop(Exception):
    """The loop has nothing safe left to do."""

    def __init__(self, status: str, detail: str, **fields: Any) -> None:
        super().__init__(f"{status}: {detail}")
        self.status = status
        self.detail = detail
        self.fields = fields


# --------------------------------------------------------------------------
# The two shells this module talks to
# --------------------------------------------------------------------------


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )


def _git(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return _run(["git", *args], cwd=root)


def _gh(
    args: list[str], *, repo: str | None = None
) -> subprocess.CompletedProcess[str]:
    return _run(["gh", *args, *(["--repo", repo] if repo else [])])


def _gh_json(args: list[str], *, repo: str | None = None) -> Any:
    result = _gh(args, repo=repo)
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout or "null")
    except json.JSONDecodeError:
        return None


def repository(root: Path, repo: str | None = None) -> str:
    """`owner/name` for this checkout, asked once.

    The review verdict and every pull-request read need it, and deriving it per
    call would make the loop depend on `gh` being reachable at moments where it
    has nothing else to ask.
    """
    if repo:
        return repo
    found = _gh_json(["repo", "view", "--json", "nameWithOwner"])
    if not found or not found.get("nameWithOwner"):
        raise Stop(
            BLOCKED_HUMAN,
            "could not determine the GitHub repository; pass --repo owner/name",
        )
    return str(found["nameWithOwner"])


# --------------------------------------------------------------------------
# The breadcrumb `resume` reads
# --------------------------------------------------------------------------


def save(paths: localstate.LocalPaths, **fields: Any) -> dict[str, Any]:
    """Record where the loop is, merging into what was already there.

    Every phase this file has a name for is also derivable from Git, GitHub and
    the lease ledger, which is what makes resuming safe. This file is the index
    into those facts, not a second copy of them: it says which task, branch,
    worktree and pull request to go and look at.
    """
    current = localstate.read(paths.project, {})
    current.update({k: v for k, v in fields.items() if v is not None})
    current["updated_at"] = localstate.now()
    localstate.write(paths.project, current)
    return current


def status(root: Path, paths: localstate.LocalPaths) -> dict[str, Any]:
    """What the project loop is doing, for the dashboard and for `resume`."""
    stored = localstate.read(paths.project, {})
    cooling = local.provider_cooldowns(paths)
    stored["provider_cooldowns"] = cooling
    stored.setdefault("status", "")
    try:
        ctx = coordinator.load_context(root)
        stored["completed_tasks"] = len(state.completed_tasks(ctx.progress))
        stored["remaining_tasks"] = len(
            [
                task_id
                for task_id in ctx.backlog.task_ids()
                if task_id not in state.completed_tasks(ctx.progress)
            ]
        )
    except Exception as failure:  # noqa: BLE001 - a status view must still render
        stored["error"] = str(failure)[:300]
    return stored


# --------------------------------------------------------------------------
# Safety preconditions
# --------------------------------------------------------------------------


def checkout_changes(root: Path) -> list[str]:
    """Anything uncommitted in the coordinator's own checkout."""
    result = _git(root, ["status", "--porcelain", "-uall"])
    if result.returncode != 0:
        raise Stop(
            BLOCKED_LOCAL_CHECKOUT,
            f"could not read the checkout state: {(result.stderr or '').strip()[:200]}",
        )
    return [line[3:].strip() for line in (result.stdout or "").splitlines() if line]


# The two files `reconcile` maintains. Named exactly, not by prefix: a new
# file appearing under `ops/state` is not automatically the orchestrator's to
# leave lying in the checkout.
LEDGER_PATHS = ("ops/state/progress.json", "ops/state/tasks.json")


def _is_ledger(path: str) -> bool:
    return path.replace("\\", "/").strip('"') in LEDGER_PATHS


def require_clean_checkout(root: Path) -> None:
    """Refuse to run against a checkout somebody is in the middle of editing.

    The loop pushes branches and fetches main. Doing that around unexplained
    local work is how the unexplained local work gets lost, and there is no
    version of "tidy it up automatically" that is safe -- which is why nothing
    here stashes, resets or discards anything.

    The orchestrator's own ledger is the exception, and without it the loop
    could never finish two tasks in a row. `reconcile` writes
    `ops/state/progress.json` and `tasks.json` exactly when a task newly
    completes, which is the moment the loop wants to pick up the next one; the
    following iteration then found its own bookkeeping sitting in the checkout
    and stopped as BLOCKED_LOCAL_CHECKOUT. The guard exists to protect work
    nobody can account for, and these two files are accounted for by
    definition. Every other path still stops it.
    """
    changes = [path for path in checkout_changes(root) if not _is_ledger(path)]
    if changes:
        raise Stop(
            BLOCKED_LOCAL_CHECKOUT,
            "the coordinator checkout has uncommitted changes; commit or move "
            "them before starting the project loop",
            changes=changes[:20],
        )


def forbidden_paths(changed: list[str]) -> list[str]:
    return [path for path in changed if NEVER_COMMIT.search(path)]


# --------------------------------------------------------------------------
# Branch, pull request, gates
# --------------------------------------------------------------------------


def commit_task_changes(
    root: Path, worktree: Path, task_id: int, title: str, *, base: str
) -> dict[str, Any]:
    """Commit what the workers left in the worktree, if anything is left.

    A worker usually commits its own work. When it does not, the branch has
    nothing to open a pull request with, so this finishes the job -- after the
    same two checks the branch would have to pass anyway, because a refusal
    before the commit is a refusal that never has to be reverted.
    """
    changed = local.changed_paths(root, worktree, base=base)
    violations = governance.violations(changed)
    if violations:
        raise Stop(
            BLOCKED_HUMAN,
            f"task {task_id} changed guarded paths: {', '.join(violations)}",
            findings=violations,
        )
    leaked = forbidden_paths(changed)
    if leaked:
        raise Stop(
            BLOCKED_HUMAN,
            f"task {task_id} would commit files that must never be committed: "
            + ", ".join(leaked),
            findings=leaked,
        )

    dirty = _git(worktree, ["status", "--porcelain", "-uall"]).stdout or ""
    if not dirty.strip():
        return {"committed": False, "reason": "the worker committed its own work"}
    staged = _git(worktree, ["add", "-A"])
    if staged.returncode != 0:
        raise Stop(BLOCKED_HUMAN, f"git add failed: {staged.stderr.strip()[:200]}")
    message = f"Task {task_id}: {title}"
    made = _git(worktree, ["commit", "-m", message])
    if made.returncode != 0:
        raise Stop(BLOCKED_HUMAN, f"git commit failed: {made.stderr.strip()[:200]}")
    return {"committed": True, "message": message}


def push_branch(worktree: Path, branch: str) -> None:
    """Publish the task branch. Never forced: a rejected push is information."""
    result = _git(worktree, ["push", "--set-upstream", "origin", branch])
    if result.returncode != 0:
        raise Stop(
            BLOCKED_HUMAN,
            f"could not push {branch}: {(result.stderr or '').strip()[:300]}",
        )


def ensure_pull_request(
    root: Path, task_id: int, title: str, branch: str, *, repo: str
) -> int:
    """Open the pull request, or find the one that is already open.

    The body is the canonical brief, which is what the cloud reviewer reads.
    """
    body = brief_mod.render(root, task_id)
    number, detail = delegate.ensure_pull_request(
        root, task_id, title, branch, body, repo=repo, draft=False
    )
    if number is None:
        raise Stop(BLOCKED_HUMAN, f"could not open a pull request: {detail}")
    return number


def ci_state(pull_request: int, *, repo: str) -> dict[str, Any]:
    """The required-check rollup, failing closed when it cannot be read."""
    payload = _gh_json(
        [
            "pr",
            "view",
            str(pull_request),
            "--json",
            "statusCheckRollup,mergeStateStatus,headRefOid",
        ],
        repo=repo,
    )
    if payload is None:
        return {"state": "unknown", "failing": [], "pending": [], "head": ""}

    reported = payload.get("statusCheckRollup")
    if not reported:
        # No checks reported is not "no checks failed". A pull request whose
        # workflows have not registered yet, and a truncated response, look
        # identical from here, and calling either one clean would merge without
        # any required check ever being observed. It reads as pending, so the
        # loop waits and eventually asks a person.
        return {
            "state": "pending",
            "failing": [],
            "pending": ["(no checks reported yet)"],
            "head": str(payload.get("headRefOid") or ""),
            "merge_state": str(payload.get("mergeStateStatus") or ""),
        }

    failing: list[dict[str, Any]] = []
    pending: list[str] = []
    for check in reported:
        name = str(check.get("name") or check.get("context") or "check")
        bucket = str(check.get("bucket") or "").lower()
        if not bucket:
            # A commit status rather than a check run: it reports `state`.
            raw = str(check.get("state") or check.get("conclusion") or "").lower()
            bucket = {
                "success": "pass",
                "failure": "fail",
                "error": "fail",
                "pending": "pending",
            }.get(raw, raw)
        if bucket in CI_PENDING:
            pending.append(name)
        elif bucket in CI_FAILING:
            failing.append(
                {
                    "name": name,
                    "conclusion": str(check.get("conclusion") or bucket),
                    "url": str(check.get("detailsUrl") or check.get("targetUrl") or ""),
                }
            )
    if pending:
        result = "pending"
    elif failing:
        result = "fail"
    else:
        result = "pass"
    return {
        "state": result,
        "failing": failing,
        "pending": pending,
        "head": str(payload.get("headRefOid") or ""),
        "merge_state": str(payload.get("mergeStateStatus") or ""),
    }


def wait_for(
    probe: Callable[[], dict[str, Any]],
    *,
    settled: Callable[[dict[str, Any]], bool],
    timeout_seconds: int,
    poll_seconds: int,
) -> dict[str, Any]:
    """Poll until the gate answers, or until the ceiling says ask a human."""
    deadline = time.monotonic() + max(1, timeout_seconds)
    while True:
        answer = probe()
        if settled(answer):
            return answer
        if time.monotonic() >= deadline:
            answer["timed_out"] = True
            return answer
        time.sleep(poll_seconds)


def merge_pull_request(pull_request: int, *, repo: str) -> dict[str, Any]:
    """Squash-merge, with no administrative override of any kind.

    There is deliberately no `--admin` here and no branch-protection bypass
    anywhere in this file: if GitHub refuses the merge, that refusal is the
    answer, and the loop stops with it rather than finding a way around it.
    """
    result = _gh(
        ["pr", "merge", str(pull_request), "--squash", "--delete-branch"], repo=repo
    )
    if result.returncode != 0:
        return {
            "merged": False,
            "reason": (result.stderr or result.stdout or "").strip()[:300],
        }
    return {"merged": True}


def fetch_main(root: Path) -> None:
    """Bring `origin/main` up to date without touching the working tree.

    A fetch moves no files and loses nothing. Fast-forwarding the checkout is
    done only when it is provably safe: on main, with nothing uncommitted, and
    only as a fast-forward.
    """
    fetched = _git(root, ["fetch", "origin", "main"])
    if fetched.returncode != 0:
        raise Stop(
            BLOCKED_HUMAN,
            "could not fetch origin/main: "
            + (fetched.stderr or fetched.stdout or "").strip()[:200],
        )
    branch = (_git(root, ["rev-parse", "--abbrev-ref", "HEAD"]).stdout or "").strip()
    if branch != "main" or checkout_changes(root):
        return
    advanced = _git(root, ["merge", "--ff-only", "origin/main"])
    if advanced.returncode != 0:
        # Not recoverable from here without rewriting somebody's history, which
        # is exactly what this module does not do. Selecting the next task from
        # a stale main is how a dependent task starts against code main has not
        # got, so it stops instead.
        raise Stop(
            BLOCKED_HUMAN,
            "main could not be fast-forwarded: "
            + (advanced.stderr or advanced.stdout or "").strip()[:200],
        )


# --------------------------------------------------------------------------
# Repairing what CI or review found
# --------------------------------------------------------------------------


def ci_findings(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Failing checks, in the shape the repair prompt already speaks.

    # ponytail: the check name and its URL, not its log. The repository's own
    # gate reproduces every required check locally, so the repair worker is
    # told to run it rather than handed a scraped transcript; fetch the log
    # here only if a check turns up that cannot be reproduced locally.
    """
    return [
        {
            "severity": "blocker",
            "confidence": "high",
            "file": "",
            "line": None,
            "requirement": f"the required check {check['name']} must pass",
            "repair": (
                f"reproduce it locally with ./scripts/check.ps1, fix the cause, "
                f"and leave the check green ({check.get('conclusion')}; "
                f"{check.get('url') or 'no url'})"
            ),
        }
        for check in checks
    ]


def review_findings(verdict: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Unresolved review threads, in the same shape."""
    return [
        {
            "severity": "blocker",
            "confidence": "high",
            "file": finding.get("path") or "",
            "line": finding.get("line"),
            "requirement": "an unresolved review thread on this pull request",
            "repair": str(finding.get("summary") or "address the reviewer's comment"),
        }
        for finding in verdict.get("findings") or []
    ]


def repair_in_worktree(
    root: Path,
    paths: localstate.LocalPaths,
    *,
    task_id: int,
    worktree: Path,
    branch: str,
    findings: list[dict[str, Any]],
    verification_kind: str,
) -> dict[str, Any]:
    """Fix exactly these findings, in the worktree the task already has.

    The same worktree, the same branch and the same base commit: a repair that
    started a fresh checkout would lose whatever is not yet pushed and would
    re-review a diff nobody produced.
    """
    config = localstate.load_config(paths)
    ctx = coordinator.load_context(root)
    ctx.tasks = local.load_leases(root, paths)
    local.merge_local_health(paths, ctx)
    store = approvals.load(paths)

    task = ctx.backlog.tasks.get(task_id)
    if task is None:
        raise Stop(BLOCKED_HUMAN, f"task {task_id} is not canonical")
    candidate = coordinator.evaluate(ctx, task, ignore_own_lease=True)

    def replan(exclude: frozenset[str]) -> Any | None:
        local.merge_local_health(paths, ctx)
        return local.local_plan(
            ctx, candidate, store, exclude_lanes=exclude, config=config
        ).writer

    writer = replan(frozenset())
    if writer is None:
        raise Stop(
            BLOCKED_WAITING_PROVIDER,
            f"no permitted lane can repair task {task_id} right now",
        )

    base = local.task_baseline(paths, task_id, worktree=worktree)
    attempted = local.implement_with_failover(
        root,
        paths,
        task_id=task_id,
        assignment=writer,
        worktree=worktree,
        config=config,
        policy=ctx.policy,
        prompt=local.repair_prompt(root, task_id, findings),
        role="implement",
        popen=None,
        tasks=ctx.tasks,
        replan=replan,
    )
    if attempted["blocked"]:
        raise Stop(BLOCKED_WAITING_PROVIDER, attempted["blocked"])
    if not attempted["run"].get("ok"):
        raise Stop(
            BLOCKED_HUMAN,
            f"the repair worker did not finish: {attempted['run'].get('outcome')}",
            findings=findings,
        )

    verification = local.verify(
        root, paths, worktree, kind=verification_kind, owner=f"project-{task_id}"
    )
    if not verification["ok"]:
        raise Stop(
            BLOCKED_HUMAN,
            f"the repair for task {task_id} did not pass verification",
            findings=findings
            + [{"requirement": "verification", "repair": "see above"}],
        )

    commit_task_changes(
        root, worktree, task_id, "repair the findings the gates reported", base=base
    )
    push_branch(worktree, branch)
    return {"repaired": True, "findings": len(findings)}


# --------------------------------------------------------------------------
# One task, all the way to merged
# --------------------------------------------------------------------------


def ship(
    root: Path,
    paths: localstate.LocalPaths,
    *,
    task_id: int,
    title: str,
    branch: str,
    worktree: Path,
    repo: str,
    verification_kind: str,
    poll_seconds: int,
    gate_timeout_seconds: int,
) -> dict[str, Any]:
    """Take one verified, reviewed task from its worktree to merged on main."""
    ctx = coordinator.load_context(root)
    max_cycles = int(ctx.policy["escalation"]["max_ci_repair_cycles"])
    reviewer_login = str(
        (ctx.policy["lanes"].get("codex_cloud") or {}).get("review_bot_login") or ""
    )

    base = local.task_baseline(paths, task_id, worktree=worktree)
    save(paths, task_id=task_id, branch=branch, worktree=str(worktree), phase="pushing")
    commit_task_changes(root, worktree, task_id, title, base=base)
    push_branch(worktree, branch)

    number = ensure_pull_request(root, task_id, title, branch, repo=repo)
    save(paths, pull_request=number, phase="waiting_for_ci")

    for cycle in range(max_cycles + 1):
        checks = wait_for(
            lambda: ci_state(number, repo=repo),
            settled=lambda answer: answer["state"] != "pending",
            timeout_seconds=gate_timeout_seconds,
            poll_seconds=poll_seconds,
        )
        save(paths, phase="waiting_for_ci", ci=checks["state"])
        if checks.get("timed_out"):
            raise Stop(
                BLOCKED_HUMAN,
                f"required checks on pull request {number} were still pending "
                f"after {gate_timeout_seconds}s",
                pull_request=number,
            )
        if checks["state"] == "unknown":
            raise Stop(
                BLOCKED_HUMAN,
                f"could not read the checks on pull request {number}; refusing "
                "to merge on a question mark",
                pull_request=number,
            )
        if checks["state"] == "fail":
            if cycle >= max_cycles:
                raise Stop(
                    BLOCKED_HUMAN,
                    f"required checks still failing after {max_cycles} repairs",
                    pull_request=number,
                    findings=checks["failing"],
                )
            save(paths, phase="repairing_ci")
            repair_in_worktree(
                root,
                paths,
                task_id=task_id,
                worktree=worktree,
                branch=branch,
                findings=ci_findings(checks["failing"]),
                verification_kind=verification_kind,
            )
            continue

        save(paths, phase="waiting_for_review")
        verdict = wait_for(
            lambda: review_mod.verdict(
                repo,
                number,
                require_submitted_review=True,
                reviewer_login=reviewer_login or None,
            ),
            settled=lambda answer: (
                answer.get("verdict")
                in (
                    "pass",
                    "changes_requested",
                )
            ),
            timeout_seconds=gate_timeout_seconds,
            poll_seconds=poll_seconds,
        )
        save(paths, phase="waiting_for_review", review=str(verdict.get("verdict")))
        if verdict.get("timed_out") or verdict.get("verdict") not in (
            "pass",
            "changes_requested",
        ):
            raise Stop(
                BLOCKED_HUMAN,
                f"no usable review verdict for pull request {number}: "
                f"{verdict.get('reason') or verdict.get('verdict')}",
                pull_request=number,
            )
        if verdict["verdict"] == "changes_requested":
            if cycle >= max_cycles:
                raise Stop(
                    BLOCKED_HUMAN,
                    f"review still requesting changes after {max_cycles} repairs",
                    pull_request=number,
                    findings=verdict.get("findings") or [],
                )
            save(paths, phase="repairing_review")
            repair_in_worktree(
                root,
                paths,
                task_id=task_id,
                worktree=worktree,
                branch=branch,
                findings=review_findings(verdict),
                verification_kind=verification_kind,
            )
            continue

        save(paths, phase="merging")
        merged = merge_pull_request(number, repo=repo)
        if not merged["merged"]:
            raise Stop(
                BLOCKED_HUMAN,
                f"GitHub refused to merge pull request {number}: {merged['reason']}",
                pull_request=number,
            )
        localstate.append_event(
            paths, "task_merged", task_id=task_id, pull_request=number
        )
        return {"task_id": task_id, "pull_request": number, "merged": True}

    raise Stop(
        BLOCKED_HUMAN,
        f"pull request {number} did not reach a clean state within its budget",
        pull_request=number,
    )


# --------------------------------------------------------------------------
# The loop
# --------------------------------------------------------------------------


def in_flight(
    ctx: coordinator.Context, paths: localstate.LocalPaths
) -> dict[str, Any] | None:
    """The task a previous run left finished and waiting, if there is one.

    Without this, a run interrupted after `ready_for_pr` could not be resumed:
    the next start called `run_once`, which correctly refuses to re-dispatch a
    task that is already waiting for its pull request, and the loop read that
    refusal as a human blocker. The breadcrumb plus the lease say which task it
    is; `ship` is idempotent, so it picks the branch and pull request back up.
    """
    stored = localstate.read(paths.project, {})
    raw = stored.get("task_id")
    if raw is None:
        return None
    task_id = int(raw)
    if task_id in state.completed_tasks(ctx.progress):
        return None
    if local.settled_locally(ctx.tasks, task_id) != "ready_for_pr":
        return None
    branch = str(stored.get("branch") or "")
    worktree = Path(str(stored.get("worktree") or ""))
    if not branch or not worktree.exists():
        return None
    return {
        "dispatched": True,
        "task_id": task_id,
        "branch": branch,
        "worktree": str(worktree),
        "outcome": "ready_for_pr",
        "detail": "resumed from the recorded project state",
        "resumed": True,
    }


def _outstanding(ctx: coordinator.Context) -> list[int]:
    done = state.completed_tasks(ctx.progress)
    return [task_id for task_id in ctx.backlog.task_ids() if task_id not in done]


def _mark_runtime(
    paths: localstate.LocalPaths, root: Path, phase: str, **fields: Any
) -> None:
    """Record this coordinator process, in the shape `cli stop` reads.

    The pid is written with the image name beside it so a stale record cannot
    be mistaken for a live run after the number is reused; nothing here decides
    liveness, `localstate.process_alive` does.
    """
    record: dict[str, Any] = {
        "pid": os.getpid(),
        "image": Path(sys.executable).name,
        "state": phase,
        "root": str(root),
        **fields,
    }
    if phase != "running":
        record["stopped_at"] = localstate.now()
    localstate.write(paths.runtime, record)


def run_project(
    root: Path,
    paths: localstate.LocalPaths,
    *,
    repo: str | None = None,
    verification: str = "gated",
    max_tasks: int | None = None,
    poll_seconds: int = DEFAULT_POLL_SECONDS,
    gate_timeout_seconds: int = DEFAULT_GATE_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Work the backlog until it is finished or something needs a person.

    One task is in flight at a time, by construction: the next task is not even
    selected until the previous one is merged and reconciled, which is what
    keeps a dependent task from starting before its prerequisite lands.
    """
    localstate.ensure(paths)
    started = datetime.now(UTC)
    merged: list[dict[str, Any]] = []
    save(paths, status=RUNNING, started_at=localstate.now(), phase="starting")
    # The same record `cli run` writes, for the same two reasons: `cli stop`
    # signals whatever pid is in it, and the dashboard shows the coordinator as
    # running rather than showing workers with nothing above them. Without it a
    # project run was unstoppable and invisible.
    _mark_runtime(paths, root, "running", started_at=localstate.now())

    try:
        # Cheapest and most local question first: an unauthorised machine is
        # not a reason to go and ask GitHub anything.
        config = localstate.load_config(paths)
        authorized, why = local.local_authorized(config)
        if not authorized:
            raise Stop(BLOCKED_HUMAN, why)
        require_clean_checkout(root)
        target = repository(root, repo)

        while True:
            require_clean_checkout(root)
            reconcile_mod.reconcile(root, repo=target)

            ctx = coordinator.load_context(root)
            ctx.tasks = local.load_leases(root, paths)
            if not _outstanding(ctx):
                break
            if max_tasks is not None and len(merged) >= max_tasks:
                # A bounded run that did what it was asked is not a completed
                # project, and saying so would mark the backlog finished.
                save(paths, status=RUNNING, phase="paused", detail="task limit reached")
                _mark_runtime(paths, root, "stopped")
                return {
                    "status": RUNNING,
                    "detail": f"stopped after {max_tasks} task(s) as asked",
                    "merged": merged,
                    "elapsed_seconds": round(
                        (datetime.now(UTC) - started).total_seconds(), 1
                    ),
                }

            save(paths, phase="selecting")
            result = in_flight(ctx, paths) or local.run_once(
                root, paths, verification_kind=verification, review=True
            )
            if not result.get("dispatched"):
                raise Stop(
                    BLOCKED_HUMAN,
                    str(result.get("reason") or "no task could be dispatched"),
                    rejections=result.get("rejections") or [],
                )

            task_id = int(result["task_id"])
            detail = str(result.get("detail") or "")
            if result.get("outcome") != "ready_for_pr":
                waiting = (
                    result.get("outcome") == local.WAITING_PROVIDER
                    or BLOCKED_WAITING_PROVIDER in detail
                )
                status_name = BLOCKED_WAITING_PROVIDER if waiting else BLOCKED_HUMAN
                raise Stop(
                    status_name,
                    f"task {task_id} ended as {result.get('outcome')}: {detail}",
                    task_id=task_id,
                    findings=(result.get("review") or {}).get("findings") or [],
                )

            task = ctx.backlog.tasks.get(task_id)
            shipped = ship(
                root,
                paths,
                task_id=task_id,
                title=task.title if task else str(result["branch"]),
                branch=str(result["branch"]),
                worktree=Path(str(result["worktree"])),
                repo=target,
                verification_kind=verification,
                poll_seconds=poll_seconds,
                gate_timeout_seconds=gate_timeout_seconds,
            )

            save(paths, phase="reconciling")
            reconcile_mod.reconcile(root, repo=target)
            fetch_main(root)

            # Proof, not assumption. If the merge did not reach the ledger the
            # next pass would select the same task again and redo work that has
            # already landed, so the loop stops instead.
            after = coordinator.load_context(root)
            if task_id not in state.completed_tasks(after.progress):
                raise Stop(
                    BLOCKED_HUMAN,
                    f"pull request {shipped['pull_request']} merged but task "
                    f"{task_id} was not reconciled as complete",
                    task_id=task_id,
                )

            local.remove_worktree(root, Path(str(result["worktree"])))
            merged.append(shipped)
            save(paths, phase="task_merged", merged=len(merged))

    except Stop as stop:
        save(paths, status=stop.status, phase="stopped", detail=stop.detail)
        localstate.append_event(
            paths, "project_stopped", status=stop.status, detail=stop.detail
        )
        _mark_runtime(paths, root, "stopped", detail=stop.detail)
        return {
            "status": stop.status,
            "detail": stop.detail,
            "merged": merged,
            "elapsed_seconds": round((datetime.now(UTC) - started).total_seconds(), 1),
            **stop.fields,
        }

    save(paths, status=COMPLETE, phase="complete", detail="")
    localstate.append_event(paths, "project_complete", merged=len(merged))
    _mark_runtime(paths, root, "stopped")
    return {
        "status": COMPLETE,
        "detail": "every canonical task is complete",
        "merged": merged,
        "elapsed_seconds": round((datetime.now(UTC) - started).total_seconds(), 1),
    }
