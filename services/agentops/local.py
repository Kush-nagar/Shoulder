"""The local execution layer.

Everything this system already knows how to decide -- what to work on, who
should do it, which model, what the brief says, what a branch may not change --
is decided by the modules around this one. None of it is repeated here. What
was missing was the part that actually runs: a worktree to work in, a headless
Claude process to do the work, a verdict about what came back, and a way to
pick the pieces up again after the machine or the process dies.

Isolation is the point of the worktree. Two writers in one checkout is the
failure the lease exists to prevent, and a lease cannot prevent it on its own if
both writers share a working tree. One task, one branch, one directory.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from services.agentops import (
    approvals,
    classify,
    coordinator,
    executors,
    governance,
    leases,
    localstate,
    routing,
    state,
    toolchain,
)
from services.agentops import (
    brief as brief_mod,
)

Runner = Callable[..., subprocess.CompletedProcess[str]]

# The harness constants live with the harnesses now; these names stay so
# callers and tests have one place to reach for them.
CLAUDE_BINARY = executors.CLAUDE_BINARY
OPENCODE_BINARY = executors.OPENCODE_BINARY

# OpenRouter speaks the Anthropic protocol at this address, which is why the
# same harness can drive either provider. These are the variable names the
# cloud worker already uses; keeping them identical means one thing is proven
# in both places rather than two things proven separately.
OPENROUTER_BASE_URL = executors.OPENROUTER_BASE_URL
OPENROUTER_KEY_ENV = executors.OPENROUTER_KEY_ENV

PROVIDERS = ("claude", "openrouter")

# Which installed capability a worker is pointed at, by role. This is a note in
# the brief, not a framework: the skills already exist, and naming every one of
# them on every worker is how a worker ends up doing none of them.
ROLE_SKILLS: dict[str, tuple[str, ...]] = {
    "implement": (
        "superpowers:test-driven-development",
        "superpowers:verification-before-completion",
        "ponytail (full)",
        "caveman (concise reporting)",
    ),
    "review": (
        "/code-review",
        "/security-review for auth, RLS, storage or deletion paths",
        "ponytail:ponytail-review",
    ),
    "scout": ("caveman:cavecrew-investigator",),
    "summarize": ("caveman (ultra)",),
    "smoke": ("caveman (ultra)",),
}

PLAN_SKILLS = (
    "superpowers:brainstorming",
    "superpowers:writing-plans",
)
DEBUG_SKILLS = ("superpowers:systematic-debugging",)


def worktree_root(root: Path, config: Mapping[str, Any]) -> Path:
    """Where worker checkouts live: beside the repository, never inside it."""
    configured = str(config.get("worktree_root") or "").strip()
    if configured:
        return Path(configured)
    return root.parent / f"{root.name.split('-')[0]}-agents"


def worktree_path(root: Path, config: Mapping[str, Any], branch: str) -> Path:
    return worktree_root(root, config) / branch


def _git(
    root: Path, args: list[str], *, runner: Runner | None = None
) -> subprocess.CompletedProcess[str]:
    execute = runner or subprocess.run
    return execute(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )


def create_worktree(
    root: Path,
    branch: str,
    path: Path,
    *,
    base: str = "HEAD",
    runner: Runner | None = None,
) -> dict[str, Any]:
    """Give this task its own checkout, reusing one that already exists.

    Reuse matters for recovery: an interrupted worker's partial implementation
    is in its worktree, and recreating the directory would throw the work away
    to save a `git worktree add`.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return {"created": False, "path": str(path), "branch": branch}

    existing = _git(root, ["rev-parse", "--verify", branch], runner=runner)
    args = (
        ["worktree", "add", str(path), branch]
        if existing.returncode == 0
        else ["worktree", "add", "-b", branch, str(path), base]
    )
    result = _git(root, args, runner=runner)
    if result.returncode != 0:
        raise RuntimeError(
            f"could not create a worktree for {branch}: "
            f"{(result.stderr or result.stdout or '').strip()[:300]}"
        )
    return {"created": True, "path": str(path), "branch": branch}


def remove_worktree(
    root: Path, path: Path, *, runner: Runner | None = None
) -> dict[str, Any]:
    """Remove a worktree. Only ever called for finished or throwaway work."""
    result = _git(root, ["worktree", "remove", "--force", str(path)], runner=runner)
    if result.returncode != 0 and path.exists():
        shutil.rmtree(path, ignore_errors=True)
        _git(root, ["worktree", "prune"], runner=runner)
    return {"removed": not path.exists(), "path": str(path)}


def provider_status(config: Mapping[str, Any]) -> dict[str, Any]:
    """Whether the configured provider can actually run right now.

    A missing OpenRouter key is not a failure. The lane is implemented and
    stays selectable; it simply cannot run until the key is in the environment,
    which is a state the operator can see and fix rather than a crash. The same
    is true of a harness that has never been installed.
    """
    provider = str(config.get("provider") or "claude")
    if provider not in PROVIDERS:
        return {
            "provider": provider,
            "status": "UNKNOWN",
            "harness": "",
            "reason": f"unknown provider; expected one of {', '.join(PROVIDERS)}",
        }
    executor = executors.for_lane(
        "openrouter" if provider == "openrouter" else "claude_subscription"
    )
    ok, reason = executor.available()
    return {
        "provider": provider,
        "harness": executor.name,
        "status": "AVAILABLE" if ok else "AVAILABLE_LATER",
        "reason": reason,
    }


def harness_status() -> dict[str, dict[str, Any]]:
    """Every harness this machine could run, and why one cannot."""
    return executors.availability()


def child_env(
    config: Mapping[str, Any], base: Mapping[str, str] | None = None
) -> dict[str, str]:
    """The environment a worker process runs with.

    Kept for the native path and for callers that want to see it. The key is
    read at spawn time, straight from the parent environment, by the harness
    that needs it -- never written to configuration, state, an event or a log.
    """
    env = dict(base if base is not None else os.environ)
    if str(config.get("provider") or "claude") != "openrouter":
        return env
    key = os.environ.get(OPENROUTER_KEY_ENV, "").strip()
    if not key:
        raise RuntimeError(
            f"{OPENROUTER_KEY_ENV} is not set; "
            "switch the provider back to claude or set the key"
        )
    env[OPENROUTER_KEY_ENV] = key
    return env


def role_budget(config: Mapping[str, Any], role: str) -> dict[str, int]:
    roles = config.get("roles") or {}
    default = localstate.DEFAULT_CONFIG["roles"].get(
        role, {"max_turns": 20, "timeout_seconds": 900}
    )
    budget = {**default, **(roles.get(role) or {})}
    return {
        "max_turns": int(budget["max_turns"]),
        "timeout_seconds": int(budget["timeout_seconds"]),
    }


def executor_argv(
    model: str,
    role: str,
    worktree: Path,
    config: Mapping[str, Any],
    lane: str = "claude_subscription",
) -> list[str]:
    """The harness command line for this lane, without the prompt."""
    executor = executors.for_lane(lane)
    return executor.argv(model, role, worktree, role_budget(config, role))


def skill_line(role: str, *, planning: bool = False, repairing: bool = False) -> str:
    """One line telling the worker which installed capability to reach for."""
    skills = list(ROLE_SKILLS.get(role, ()))
    if planning:
        skills = list(PLAN_SKILLS) + skills
    if repairing:
        skills = list(DEBUG_SKILLS) + skills
    if not skills:
        return ""
    return (
        "Use these installed capabilities where they apply, and no others: "
        + ", ".join(skills)
        + "."
    )


def run_worker(
    root: Path,
    paths: localstate.LocalPaths,
    *,
    prompt: str,
    model: str,
    role: str,
    worktree: Path,
    config: Mapping[str, Any],
    lane: str = "claude_subscription",
    run_id: str | None = None,
    popen: Callable[..., Any] | None = None,
    on_spawn: Callable[[int], None] | None = None,
) -> dict[str, Any]:
    """Run one worker in the harness its lane runs in.

    Which harness is not a new decision: the router already chose the lane, and
    policy already confines each model family to a lane, so the lane says which
    of the two harnesses starts.
    """
    executor = executors.for_lane(lane)
    return executors.run(
        executor,
        paths,
        prompt=prompt,
        model=model,
        role=role,
        worktree=worktree,
        budget=role_budget(config, role),
        run_id=run_id,
        popen=popen,
        on_spawn=on_spawn,
    )


def build_prompt(
    root: Path,
    task_id: int,
    role: str,
    *,
    repair: str | None = None,
    planning: bool = False,
) -> str:
    """The task packet: the existing brief plus one line of skill routing."""
    packet = brief_mod.render(root, task_id, repair=repair)
    line = skill_line(role, planning=planning, repairing=bool(repair))
    return f"{packet}\n\n### Capabilities\n\n{line}\n"


def worker_image(lane: str = "claude_subscription") -> str:
    return executors.worker_image(executors.for_lane(lane))


def resolve_uv(root: Path, paths: localstate.LocalPaths) -> Path:
    return toolchain.resolve_uv(root, paths)


# --------------------------------------------------------------------------
# Local execution authorisation
# --------------------------------------------------------------------------

# Cloud autonomy and local execution are different permissions with different
# blast radii. `ops/policy.json` decides whether this system may write code
# unattended in GitHub Actions, on credentials nobody is watching; it is
# governance, it stays off, and nothing here touches it. Whether an operator
# may run a worker on their own workstation, having just typed the command, is
# a different question, and answering it by reading the cloud switch meant the
# local runtime could not be used at all without granting the cloud one.
#
# So local execution has its own switch, in ignored local state. It is set only
# by an explicit local command. Importing a module does not set it, and neither
# does loading the dashboard, which is why neither can start work.
LOCAL_INTENT_HINT = (
    "start the local runtime explicitly: ./scripts/agentops-local.ps1 start "
    "(or: python -m services.agentops.cli run --enable)"
)


def local_authorized(config: Mapping[str, Any]) -> tuple[bool, str]:
    """Whether an operator has explicitly authorised local execution."""
    if not bool(config.get("local_enabled")):
        return False, (
            "local execution is not enabled on this machine; " + LOCAL_INTENT_HINT
        )
    at = str(config.get("local_enabled_at") or "unknown time")
    by = str(config.get("local_enabled_by") or "an operator")
    return True, f"local execution enabled by {by} at {at}"


def enable_local(paths: localstate.LocalPaths, *, by: str = "") -> dict[str, Any]:
    """Record explicit local operator intent. Never touches cloud policy."""
    config = localstate.load_config(paths)
    config["local_enabled"] = True
    config["local_enabled_at"] = localstate.now()
    config["local_enabled_by"] = by or os.environ.get("USERNAME") or "operator"
    localstate.save_config(paths, config)
    localstate.append_event(paths, "local_enabled", by=config["local_enabled_by"])
    return config


def disable_local(paths: localstate.LocalPaths) -> dict[str, Any]:
    """Stop local scheduling. Cloud policy is not consulted or changed."""
    config = localstate.load_config(paths)
    config["local_enabled"] = False
    config["local_disabled_at"] = localstate.now()
    localstate.save_config(paths, config)
    localstate.append_event(paths, "local_disabled")
    return config


# --------------------------------------------------------------------------
# Planning, with approval and harness availability folded in
# --------------------------------------------------------------------------


@dataclass
class LocalPlan:
    """What the router decided, once local constraints are applied."""

    candidate: Any
    classification: Any
    capability_class: str
    branch: str
    writer: Any | None = None
    reviewer: Any | None = None
    reviewer_independent: bool = True
    blocked_reason: str | None = None
    rejections: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.candidate.task.id,
            "task_title": self.candidate.task.title,
            "branch": self.branch,
            "capability_class": self.capability_class,
            "classification": self.classification.as_dict(),
            "writer": self.writer.as_dict() if self.writer else None,
            "reviewer": self.reviewer.as_dict() if self.reviewer else None,
            "reviewer_independent": self.reviewer_independent,
            "blocked_reason": self.blocked_reason,
            "rejections": self.rejections,
        }


def unavailable_lanes(policy: Mapping[str, Any]) -> dict[str, str]:
    """Lanes whose harness cannot run on this machine right now.

    A lane the router would happily choose is useless locally if its harness is
    not installed or its key is absent, and discovering that after taking a
    lease wastes an attempt. Cloud-only lanes are excluded here for the same
    reason: locally there is nothing to run them with.
    """
    out: dict[str, str] = {}
    for name, lane in (policy.get("lanes") or {}).items():
        harness = str(lane.get("harness") or "")
        if harness in ("codex-cloud-github", "codex-action"):
            out[name] = f"{name}: {harness} runs in the cloud, not locally"
            continue
        ok, reason = executors.for_lane(name).available()
        if not ok:
            out[name] = f"{name}: {reason}"
    return out


def local_plan(
    ctx: Any,
    candidate: Any,
    store: dict[str, Any],
    *,
    escalations: int = 0,
    exclude_lanes: frozenset[str] = frozenset(),
    purpose: str = "task",
) -> LocalPlan:
    """The existing router, asked the question with local constraints attached.

    Approval and harness availability are expressed as inputs -- an unapproved
    model is not a qualified candidate, an unavailable lane is an excluded lane
    -- so the router, its rejection messages, its fallback chain and its
    escalation ladder all keep working without a second router existing.
    """
    classification = classify.classify(candidate.task, prior_failures=escalations)
    branch = coordinator.branch_name(candidate.task, candidate.block)
    inputs = ctx.routing_inputs()
    class_name = routing.capability_class(inputs.policy, classification)
    gated = approvals.gate_inputs(
        inputs, store, capability_class=class_name, purpose=purpose
    )

    unusable = unavailable_lanes(inputs.policy)
    excluded = frozenset(exclude_lanes) | frozenset(unusable)
    plan = LocalPlan(
        candidate=candidate,
        classification=classification,
        capability_class=class_name,
        branch=branch,
        rejections=list(unusable.values()),
    )

    try:
        plan.writer = routing.select(
            gated,
            classification,
            effort_escalations=escalations,
            exclude_lanes=excluded,
        )
    except routing.RoutingBlocked as blocked:
        plan.blocked_reason = blocked.reason
        plan.rejections.extend(blocked.rejections)
        return plan

    plan.rejections.extend(plan.writer.rejections)

    try:
        plan.reviewer = routing.select_reviewer(gated, classification, plan.writer)
    except routing.RoutingBlocked as blocked:
        # Independence is the ideal and is not always purchasable locally: with
        # only one provider family installed there is no other family to ask.
        # Reviewing with a same-family reviewer and saying so is better than
        # either skipping review or refusing to work at all -- and the cloud
        # review on the pull request, which is independent, still happens.
        plan.rejections.extend(blocked.rejections)
        try:
            plan.reviewer = routing.select(
                gated, classification, purpose="review", exclude_lanes=excluded
            )
            plan.reviewer_independent = False
        except routing.RoutingBlocked as also_blocked:
            plan.blocked_reason = f"no reviewer available: {also_blocked.reason}"
            plan.rejections.extend(also_blocked.rejections)
    return plan


# --------------------------------------------------------------------------
# Review findings
# --------------------------------------------------------------------------

BLOCKING_SEVERITIES = ("blocker", "major")
BLOCKING_CONFIDENCE = ("high", "medium")

REVIEW_SCHEMA = """Reply with one JSON object and nothing else:

{"verdict": "pass" | "changes_requested",
 "summary": "<one sentence>",
 "findings": [
   {"severity": "blocker|major|minor|nit",
    "confidence": "high|medium|low",
    "file": "<path or empty>",
    "line": <number or null>,
    "requirement": "<the rule or invariant this breaks>",
    "repair": "<the smallest change that fixes it>"}
 ]}

Report only defects you can point at in the diff. A style preference is `nit`
with `low` confidence. Do not restate what the code does."""


def parse_findings(text: str) -> dict[str, Any]:
    """The reviewer's verdict, read from whatever it actually replied with.

    A reviewer that answers in prose has still reviewed; the run is not thrown
    away over formatting. But an unreadable verdict is never read as a pass,
    because "could not tell" and "looks fine" are different answers.
    """
    if not text:
        return {"verdict": "unreadable", "summary": "", "findings": []}
    candidates = [text]
    if "```" in text:
        for chunk in text.split("```"):
            chunk = chunk.strip()
            if chunk.startswith("json"):
                chunk = chunk[4:].strip()
            if chunk.startswith("{"):
                candidates.insert(0, chunk)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidates.insert(0, text[start : end + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        findings = parsed.get("findings")
        return {
            "verdict": str(parsed.get("verdict") or "changes_requested"),
            "summary": str(parsed.get("summary") or "")[:400],
            "findings": [f for f in (findings or []) if isinstance(f, dict)],
        }
    return {"verdict": "unreadable", "summary": text[:400], "findings": []}


def blocking_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The findings that must be fixed before this task can be finished.

    A low-confidence style note is recorded and does not block: leaving the
    loop hostage to taste is how a repair budget gets spent on rewording a
    comment.
    """
    blocking = []
    for finding in findings:
        severity = str(finding.get("severity") or "").lower()
        confidence = str(finding.get("confidence") or "high").lower()
        if severity in BLOCKING_SEVERITIES and confidence in BLOCKING_CONFIDENCE:
            blocking.append(finding)
    return blocking


def review_prompt(root: Path, task_id: int, diff: str, changed: list[str]) -> str:
    """What the reviewer is asked, and what it is allowed to look at."""
    packet = brief_mod.render(root, task_id)
    files = "\n".join(f"- `{path}`" for path in changed) or "- (no files changed)"
    return (
        "You are reviewing an implementation. You may read files and run read-only\n"
        "commands. You may not edit anything: report findings instead.\n\n"
        f"### Files changed\n\n{files}\n\n"
        f"### Diff\n\n```diff\n{diff[:60000]}\n```\n\n"
        f"### The canonical requirements\n\n{packet}\n\n"
        f"### How to answer\n\n{REVIEW_SCHEMA}\n"
    )


def repair_prompt(root: Path, task_id: int, findings: list[dict[str, Any]]) -> str:
    """The repair worker gets the exact findings, and only those."""
    lines = []
    for index, finding in enumerate(findings, start=1):
        where = finding.get("file") or "unknown file"
        line = finding.get("line")
        where = f"{where}:{line}" if line else where
        lines.append(
            f"{index}. [{finding.get('severity')}/{finding.get('confidence')}] "
            f"{where}\n   requirement: {finding.get('requirement')}\n"
            f"   repair: {finding.get('repair')}"
        )
    findings_text = "\n".join(lines) or "(none recorded)"
    packet = brief_mod.render(root, task_id, repair="review findings")
    return (
        "A reviewer found the problems below in your branch. Fix exactly these,\n"
        "in the smallest way that is correct, and change nothing else.\n\n"
        f"### Findings\n\n{findings_text}\n\n{packet}\n\n"
        f"### Capabilities\n\n{skill_line('implement', repairing=True)}\n"
    )


def diff_of(root: Path, worktree: Path, *, runner: Runner | None = None) -> str:
    """The change under review, committed or not."""
    tracked = _git(worktree, ["diff", "HEAD"], runner=runner)
    untracked = _git(
        worktree, ["ls-files", "--others", "--exclude-standard"], runner=runner
    )
    parts = [tracked.stdout or ""]
    for name in (untracked.stdout or "").splitlines():
        name = name.strip()
        if not name:
            continue
        path = worktree / name
        try:
            body = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        parts.append(f"\n--- /dev/null\n+++ b/{name}\n" + body[:20000])
    return "\n".join(part for part in parts if part.strip())


# --------------------------------------------------------------------------
# Leases, verification, verdicts and recovery
# --------------------------------------------------------------------------


def load_leases(root: Path, paths: localstate.LocalPaths) -> dict[str, Any]:
    """The lease ledger this runtime writes to.

    Seeded once from the tracked ledger, because that is the baseline a fresh
    machine starts from, and written only to the ignored copy afterwards. The
    tracked file belongs to the cloud loop; dirtying it here would put runtime
    bookkeeping into the diff a worker is about to open a pull request for.
    """
    if paths.leases.exists():
        return localstate.read(paths.leases, {"leases": {}})
    tracked = state.read_json(state.Paths(root).tasks, {"leases": {}})
    seeded = {
        "$source": "seeded from ops/state/tasks.json; written only in .agentops",
        "leases": tracked.get("leases", {}),
    }
    localstate.write(paths.leases, seeded)
    return seeded


def save_leases(paths: localstate.LocalPaths, tasks: dict[str, Any]) -> None:
    localstate.write(paths.leases, tasks)


def changed_paths(
    root: Path,
    worktree: Path,
    *,
    base: str = "HEAD",
    runner: Runner | None = None,
) -> list[str]:
    """Every repository path this worktree has touched, committed or not.

    Governance is judged from this, so an uncommitted edit has to count: a
    branch that only stages a policy change at push time is precisely the case
    the guard exists for.
    """
    seen: set[str] = set()
    # `-uall` lists every untracked file rather than collapsing a new
    # directory to one entry: a guarded path inside a new directory would
    # otherwise reach the governance check as "ops/" and match nothing.
    status = _git(worktree, ["status", "--porcelain", "-uall"], runner=runner)
    for line in (status.stdout or "").splitlines():
        entry = line[3:].strip()
        if not entry:
            continue
        # A rename reads as "old -> new"; the new path is the one that matters.
        seen.add(entry.split(" -> ")[-1].strip('"'))
    committed = _git(worktree, ["diff", "--name-only", f"{base}...HEAD"], runner=runner)
    if committed.returncode == 0:
        seen.update(
            path.strip()
            for path in (committed.stdout or "").splitlines()
            if path.strip()
        )
    return sorted(seen)


def verify(
    root: Path,
    paths: localstate.LocalPaths,
    worktree: Path,
    *,
    kind: str = "fast",
    owner: str = "local",
    runner: Runner | None = None,
    uv: Path | None = None,
) -> dict[str, Any]:
    """Run the checks this outcome owes, serialising only what must be.

    `fast` is the Python gate and binds nothing, so two workers may run it at
    once. `gated` starts a web server and containers on fixed ports, so exactly
    one may run at a time on this machine.
    """
    binary = uv or toolchain.resolve_uv(root, paths)
    if kind == "fast":
        commands = toolchain.fast_check_commands(binary)
    elif kind == "gated":
        commands = [
            ["pwsh", "-NoProfile", "-File", str(root / "scripts" / "check.ps1")]
        ]
    else:
        raise ValueError(f"unknown verification kind: {kind}")

    if not any(toolchain.needs_infra_lock(command) for command in commands):
        result = toolchain.run_commands(worktree, commands, runner=runner)
        localstate.append_event(paths, "verification", kind=kind, ok=result["ok"])
        return {**result, "kind": kind, "locked": False}

    with toolchain.infra_lock(paths, owner=owner):
        result = toolchain.run_commands(worktree, commands, runner=runner)
    localstate.append_event(
        paths, "verification", kind=kind, ok=result["ok"], locked=True
    )
    return {**result, "kind": kind, "locked": True}


def classify_outcome(
    run: Mapping[str, Any],
    verification: Mapping[str, Any] | None,
    violations: list[str],
) -> str:
    """One word for what happened, in the order these things override each other.

    Governance comes first: a branch that edited what this system is permitted
    to do is refused whether or not its tests pass, because passing tests are
    not the question being asked.
    """
    if violations:
        return "governance_refused"
    if run.get("outcome") == "timeout":
        return "timeout"
    if not run.get("ok"):
        return "implementation_failed"
    if verification is None:
        return "unverified"
    if not verification.get("ok"):
        return "verification_failed"
    return "completed"


REPAIRABLE = ("implementation_failed", "verification_failed", "timeout")


def _finish(
    paths: localstate.LocalPaths,
    tasks: dict[str, Any],
    policy: Mapping[str, Any],
    task_id: int,
    outcome: str,
    *,
    once_key: str,
) -> dict[str, Any]:
    """Move the lease to wherever this outcome leaves it.

    Repairs go through the existing repair ceilings rather than a second set of
    rules, and a refused branch is never repaired: that fix is a human's, on a
    branch that is not this one.
    """
    lease = tasks.get("leases", {}).get(str(task_id), {})
    if outcome in ("completed", "ready_for_pr"):
        lease["state"] = "ready_for_pr"
        lease["heartbeat_at"] = localstate.now()
        save_leases(paths, tasks)
        return {"lease_state": "ready_for_pr", "escalated": False}

    if outcome in ("governance_refused", "blocked"):
        leases.release(tasks, task_id, "blocked")
        save_leases(paths, tasks)
        return {"lease_state": "blocked", "escalated": False}

    if outcome in REPAIRABLE:
        try:
            leases.begin_repair(
                tasks, dict(policy), task_id, reason="ci", once_key=once_key
            )
            save_leases(paths, tasks)
            return {"lease_state": "repairing", "escalated": True}
        except leases.RepairBudgetExhausted as exhausted:
            leases.release(tasks, task_id, "blocked")
            save_leases(paths, tasks)
            return {
                "lease_state": "blocked",
                "escalated": False,
                "reason": str(exhausted),
            }

    save_leases(paths, tasks)
    return {"lease_state": lease.get("state"), "escalated": False}


def _record(paths: localstate.LocalPaths, task_id: int, /, **fields: Any) -> None:
    """Update this task's worker record.

    `task_id` is positional-only so a caller may also record a field of
    its own called `task_id` without colliding with this parameter.
    """
    localstate.save_worker(paths, str(task_id), fields)


def _implement(
    root: Path,
    paths: localstate.LocalPaths,
    *,
    task_id: int,
    assignment: Any,
    worktree: Path,
    config: Mapping[str, Any],
    prompt: str,
    role: str,
    popen: Callable[..., Any] | None,
) -> dict[str, Any]:
    run = run_worker(
        root,
        paths,
        prompt=prompt,
        model=assignment.harness_model,
        role=role,
        worktree=worktree,
        config=config,
        lane=assignment.lane,
        popen=popen,
        on_spawn=lambda pid: _record(
            paths, task_id, pid=pid, image=worker_image(assignment.lane)
        ),
    )
    _record(
        paths,
        task_id,
        model=assignment.harness_model,
        lane=assignment.lane,
        harness=run.get("harness"),
        provider=run.get("provider"),
        usage=run.get("usage"),
        cost_usd=run.get("cost_usd"),
        cost_known=run.get("cost_known"),
        last_action=run.get("last_action"),
    )
    return run


def run_once(
    root: Path,
    paths: localstate.LocalPaths,
    *,
    owner: str | None = None,
    popen: Callable[..., Any] | None = None,
    runner: Runner | None = None,
    verification_kind: str = "fast",
    review: bool = True,
) -> dict[str, Any]:
    """One task, taken from assignment to ready-for-review, locally.

    The whole lifecycle lives here rather than in a second workflow engine:
    implement, verify what changed, review it, repair exactly what review
    found, re-review, verify in full, and only then call it ready for a pull
    request. Every decision inside is made by a module that already existed --
    the router picks both workers, the lease module bounds the repairs, the
    governance guard decides what a branch may not touch.
    """
    localstate.ensure(paths)
    config = localstate.load_config(paths)
    authorized, why = local_authorized(config)
    if not authorized:
        # Deliberately not the cloud switch. Cloud autonomy stays off; this is
        # about whether an operator has started the local runtime on purpose.
        return {"dispatched": False, "reason": why, "local_enabled": False}

    ctx = coordinator.load_context(root)
    ctx.tasks = load_leases(root, paths)
    store = approvals.load(paths)
    owner = owner or f"local-{os.getpid()}"

    candidate = coordinator.next_eligible(ctx)
    if candidate is None:
        return {"dispatched": False, "reason": "no eligible task"}

    plan = local_plan(ctx, candidate, store)
    if plan.writer is None or plan.blocked_reason:
        return {
            "dispatched": False,
            "reason": plan.blocked_reason or "no writer could be routed",
            "rejections": plan.rejections,
        }

    run_id = uuid.uuid4().hex[:12]
    try:
        leases.acquire(
            ctx.tasks,
            ctx.policy,
            task_id=candidate.task.id,
            owner=owner,
            branch=plan.branch,
            assignment=plan.writer.as_dict(),
            run_id=run_id,
            owner_finished=lambda held: (
                not localstate.process_alive(
                    held.get("pid"),
                    worker_image(plan.writer.lane if plan.writer else ""),
                )
            ),
        )
    except leases.LeaseConflict as conflict:
        return {"dispatched": False, "reason": str(conflict)}
    except leases.AttemptsExhausted as exhausted:
        leases.release(ctx.tasks, candidate.task.id, "blocked")
        save_leases(paths, ctx.tasks)
        return {"dispatched": False, "reason": f"BLOCKED_AUTOMATION: {exhausted}"}
    save_leases(paths, ctx.tasks)

    task_id = candidate.task.id
    worktree = worktree_path(root, config, plan.branch)
    create_worktree(root, plan.branch, worktree, runner=runner)
    _record(
        paths,
        task_id,
        task_id=task_id,
        task_title=candidate.task.title,
        role="implement",
        branch=plan.branch,
        worktree=str(worktree),
        provider=config.get("provider"),
        phase="implementing",
        run_id=run_id,
        started_at=localstate.now(),
        reviewer_independent=plan.reviewer_independent,
        escalations=[],
    )

    phases: list[dict[str, Any]] = []
    escalations: list[dict[str, Any]] = []
    writer = plan.writer
    ceilings = ctx.policy["escalation"]
    max_implementation = int(ceilings["max_implementation_attempts"])
    max_review_cycles = int(ceilings["max_review_repair_cycles"])
    outcome = "unverified"
    verification: dict[str, Any] | None = None
    verdict: dict[str, Any] = {}
    run: dict[str, Any] = {}

    def finish(final: str, detail: str = "") -> dict[str, Any]:
        result = _finish(paths, ctx.tasks, ctx.policy, task_id, final, once_key=run_id)
        _record(
            paths,
            task_id,
            phase=final,
            verification=None if verification is None else verification["ok"],
            review=verdict,
            escalations=escalations,
            finished_at=localstate.now(),
        )
        localstate.append_event(
            paths, "task_outcome", task_id=task_id, outcome=final, detail=detail
        )
        return {
            "dispatched": True,
            "task_id": task_id,
            "branch": plan.branch,
            "worktree": str(worktree),
            "assignment": writer.as_dict() if writer else None,
            "reviewer": plan.reviewer.as_dict() if plan.reviewer else None,
            "reviewer_independent": plan.reviewer_independent,
            "phases": phases,
            "escalations": escalations,
            "run": run,
            "review": verdict,
            "verification": verification,
            "outcome": final,
            "detail": detail,
            **result,
        }

    # ---------------------------------------------------- implement + verify
    for attempt in range(max_implementation):
        if attempt:
            # Escalation is the existing ladder: more effort first, then a
            # different lane, which is what moves the work across families.
            previous = writer
            skip = frozenset({previous.lane}) if attempt > 1 else frozenset()
            escalated = local_plan(
                ctx,
                candidate,
                store,
                escalations=attempt,
                exclude_lanes=skip,
            )
            if escalated.writer is not None:
                writer = escalated.writer
                escalations.append(
                    {
                        "at": localstate.now(),
                        "attempt": attempt,
                        "previous_model": previous.harness_model,
                        "previous_lane": previous.lane,
                        "failure": outcome,
                        "next_model": writer.harness_model,
                        "next_lane": writer.lane,
                        "harness": executors.for_lane(writer.lane).name,
                    }
                )
                localstate.append_event(
                    paths, "escalation", task_id=task_id, **escalations[-1]
                )

        _record(paths, task_id, phase="implementing")
        if attempt == 0:
            prompt = build_prompt(root, task_id, "implement")
        elif verdict.get("findings"):
            prompt = repair_prompt(
                root, task_id, blocking_findings(verdict["findings"])
            )
        else:
            prompt = build_prompt(root, task_id, "implement", repair="a failing check")
        run = _implement(
            root,
            paths,
            task_id=task_id,
            assignment=writer,
            worktree=worktree,
            config=config,
            prompt=prompt,
            role="implement",
            popen=popen,
        )
        phases.append({"phase": "implementing", "outcome": run["outcome"]})

        changed = changed_paths(root, worktree, runner=runner)
        violations = governance.violations(changed)
        if violations:
            outcome = "governance_refused"
            return finish(outcome, ", ".join(violations))
        if not run["ok"]:
            outcome = classify_outcome(run, None, [])
            if attempt + 1 >= max_implementation:
                return finish(outcome, "implementation attempts exhausted")
            continue

        _record(paths, task_id, phase="verifying", changed_files=changed)
        verification = verify(
            root, paths, worktree, kind="fast", owner=owner, runner=runner
        )
        phases.append({"phase": "verifying", "ok": verification["ok"]})
        if verification["ok"]:
            break
        outcome = "verification_failed"
        if attempt + 1 >= max_implementation:
            return finish(outcome, "verification still failing")
    else:
        return finish(outcome or "implementation_failed", "no attempt succeeded")

    if not run.get("ok") or verification is None or not verification["ok"]:
        return finish(outcome or "verification_failed", "targeted verification failed")

    # ----------------------------------------------------------- review loop
    if review and plan.reviewer is not None:
        for cycle in range(max_review_cycles + 1):
            _record(paths, task_id, phase="review")
            diff = diff_of(root, worktree, runner=runner)
            review_run = run_worker(
                root,
                paths,
                prompt=review_prompt(root, task_id, diff, changed),
                model=plan.reviewer.harness_model,
                role="review",
                worktree=worktree,
                config=config,
                lane=plan.reviewer.lane,
                popen=popen,
            )
            verdict = parse_findings(review_run.get("last_action", ""))
            verdict["reviewer"] = plan.reviewer.harness_model
            verdict["independent"] = plan.reviewer_independent
            verdict["cycle"] = cycle
            localstate.write(
                paths.run_dir(review_run["run_id"]) / "findings.json", verdict
            )
            phases.append(
                {
                    "phase": "review",
                    "verdict": verdict["verdict"],
                    "findings": len(verdict.get("findings", [])),
                }
            )
            _record(paths, task_id, review=verdict)

            must_fix = blocking_findings(verdict.get("findings", []))
            if not must_fix and verdict["verdict"] != "unreadable":
                break
            if verdict["verdict"] == "unreadable" and not must_fix:
                # An unreadable verdict is not a pass. It is also not a defect
                # to hand a repair worker, so it stops the task rather than
                # burning the budget on a guess.
                return finish("blocked", "the reviewer's verdict could not be read")
            if cycle >= max_review_cycles:
                return finish(
                    "blocked",
                    "review repair budget exhausted with "
                    + "; ".join(
                        str(f.get("requirement") or f.get("repair")) for f in must_fix
                    ),
                )

            try:
                leases.begin_repair(
                    ctx.tasks,
                    dict(ctx.policy),
                    task_id,
                    reason="review",
                    once_key=f"{run_id}-review-{cycle}",
                )
                save_leases(paths, ctx.tasks)
            except leases.RepairBudgetExhausted as exhausted:
                return finish("blocked", str(exhausted))

            _record(paths, task_id, phase="repairing")
            run = _implement(
                root,
                paths,
                task_id=task_id,
                assignment=writer,
                worktree=worktree,
                config=config,
                prompt=repair_prompt(root, task_id, must_fix),
                role="implement",
                popen=popen,
            )
            phases.append({"phase": "repairing", "outcome": run["outcome"]})

            changed = changed_paths(root, worktree, runner=runner)
            violations = governance.violations(changed)
            if violations:
                return finish("governance_refused", ", ".join(violations))
            if not run["ok"]:
                return finish("implementation_failed", "repair worker failed")

            _record(paths, task_id, phase="verifying", changed_files=changed)
            verification = verify(
                root, paths, worktree, kind="fast", owner=owner, runner=runner
            )
            phases.append({"phase": "verifying", "ok": verification["ok"]})
            if not verification["ok"]:
                return finish("verification_failed", "repair did not verify")

    # ------------------------------------------------------ full verification
    _record(paths, task_id, phase="verifying_full")
    verification = verify(
        root, paths, worktree, kind=verification_kind, owner=owner, runner=runner
    )
    phases.append(
        {
            "phase": "verifying_full",
            "kind": verification_kind,
            "ok": verification["ok"],
        }
    )
    if not verification["ok"]:
        return finish("verification_failed", "full verification failed")

    changed = changed_paths(root, worktree, runner=runner)
    violations = governance.violations(changed)
    if violations:
        return finish("governance_refused", ", ".join(violations))

    _record(paths, task_id, changed_files=changed)
    return finish("ready_for_pr")


EVAL_PROMPT = (
    "This is a model evaluation on a throwaway branch, not product work.\n"
    "Create a file named EVAL.md in the current working directory containing "
    "exactly two lines: the first the single word ok, the second the number of "
    "Python files under services/agentops as a bare integer.\n"
    "Change nothing else, and do not edit any existing file. "
    "Reply with the single word done."
)


def evaluate_model(
    root: Path,
    paths: localstate.LocalPaths,
    model: str,
    *,
    lane: str = "claude_subscription",
    keep: bool = False,
    popen: Callable[..., Any] | None = None,
    runner: Runner | None = None,
) -> dict[str, Any]:
    """Run one fixed task on one model and record what it cost to get it.

    The task and the harness are held constant so the numbers compare. This is
    not a benchmark suite and is not trying to be: it answers whether a
    candidate can follow a small instruction in this repository without
    wandering, which is the question an approval actually turns on.
    """
    localstate.ensure(paths)
    config = localstate.load_config(paths)
    branch = f"agentops/eval-{uuid.uuid4().hex[:8]}"
    worktree = worktree_path(root, config, branch.replace("/", "-"))
    create_worktree(root, branch, worktree, runner=runner)
    started = time.monotonic()

    run = run_worker(
        root,
        paths,
        prompt=EVAL_PROMPT,
        model=model,
        role="smoke",
        worktree=worktree,
        config=config,
        lane=lane,
        popen=popen,
    )
    marker = worktree / "EVAL.md"
    changed = changed_paths(root, worktree, runner=runner)
    violations = governance.violations(changed)
    verification = verify(
        root, paths, worktree, kind="fast", owner="evaluation", runner=runner
    )
    usage = run.get("usage") or {}

    result = {
        "model": model,
        "lane": lane,
        "harness": run.get("harness"),
        "outcome": run.get("outcome"),
        "completed_task": marker.exists(),
        "unnecessary_edits": [p for p in changed if p != "EVAL.md"],
        "governance_violations": violations,
        "tests_ok": verification["ok"],
        "turns": run.get("turns"),
        "latency_seconds": round(time.monotonic() - started, 1),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cost_usd": run.get("cost_usd"),
        "cost_known": run.get("cost_known"),
        "reason": run.get("reason", ""),
    }
    localstate.append_event(
        paths,
        "model_evaluated",
        **{k: result[k] for k in ("model", "lane", "outcome", "completed_task")},
    )
    if not keep:
        remove_worktree(root, worktree, runner=runner)
        _git(root, ["branch", "-D", branch], runner=runner)
    return result


def recover(
    root: Path, paths: localstate.LocalPaths, *, runner: Runner | None = None
) -> dict[str, Any]:
    """Work out what the last run left behind, without destroying any of it.

    An interrupted worker's partial implementation lives in its worktree, so
    nothing here deletes one. The lease is left to the ordinary stale-lease
    path, which already refuses to take a lease from an owner still running.
    """
    records = localstate.worker_records(paths)
    report: list[dict[str, Any]] = []
    for key, record in sorted(records.items()):
        worktree = Path(str(record.get("worktree") or ""))
        alive = localstate.process_alive(record.get("pid"), worker_image())
        phase = str(record.get("phase") or "")
        if alive:
            worker_state = "running"
        elif record.get("finished_at") or phase in (
            "completed",
            "governance_refused",
        ):
            worker_state = "finished"
        else:
            worker_state = "interrupted"
        report.append(
            {
                "task_id": record.get("task_id", key),
                "state": worker_state,
                "phase": phase,
                "branch": record.get("branch"),
                "worktree": str(worktree),
                "worktree_present": worktree.exists(),
            }
        )
        if worker_state != "running":
            localstate.save_worker(paths, key, {"recovery_state": worker_state})
    localstate.append_event(paths, "recovery", workers=len(report))
    return {"workers": report}


DRY_RUN_PROMPT = (
    "This is an AgentOps local runtime smoke check, not product work.\n"
    "Create a file named DRYRUN.md in the current working directory whose "
    "entire contents are the single line: local runtime ok\n"
    "Change nothing else. Do not read or edit any other file. "
    "Reply with the single word done."
)


def dry_run_lifecycle(
    root: Path,
    paths: localstate.LocalPaths,
    *,
    branch: str | None = None,
    popen: Callable[..., Any] | None = None,
    runner: Runner | None = None,
    cleanup: bool = True,
) -> dict[str, Any]:
    """Exercise the whole local path on work that is not a backlog task.

    A bootstrap needs proof the pieces fit before a real task is handed to
    them, and the only honest proof is running them. This runs on a throwaway
    branch of its own and writes one scratch file. It never selects a backlog
    task, so it cannot start one by accident.
    """
    localstate.ensure(paths)
    config = localstate.load_config(paths)
    branch = branch or f"agentops/local-dryrun-{uuid.uuid4().hex[:8]}"
    worktree = worktree_path(root, config, branch.replace("/", "-"))
    created = create_worktree(root, branch, worktree, runner=runner)

    run = run_worker(
        root,
        paths,
        prompt=DRY_RUN_PROMPT,
        model="haiku",
        role="smoke",
        worktree=worktree,
        config=config,
        popen=popen,
    )
    marker = worktree / "DRYRUN.md"
    changed = changed_paths(root, worktree, runner=runner)
    violations = governance.violations(changed)
    verification = verify(
        root, paths, worktree, kind="fast", owner="dry-run", runner=runner
    )
    outcome = classify_outcome(run, verification, violations)

    result: dict[str, Any] = {
        "branch": branch,
        "worktree": str(worktree),
        "created": created["created"],
        "run": run,
        "marker_written": marker.exists(),
        "marker_contents": (
            marker.read_text(encoding="utf-8").strip() if marker.exists() else ""
        ),
        "changed_files": changed,
        "violations": violations,
        "verification": {"ok": verification["ok"], "failed": verification["failed"]},
        "outcome": outcome,
    }
    localstate.append_event(paths, "dry_run", outcome=outcome, branch=branch)
    if cleanup:
        remove_worktree(root, worktree, runner=runner)
        _git(root, ["branch", "-D", branch], runner=runner)
        result["cleaned_up"] = not worktree.exists()
    return result


__all__ = [
    "CLAUDE_BINARY",
    "OPENROUTER_BASE_URL",
    "OPENROUTER_KEY_ENV",
    "PROVIDERS",
    "build_prompt",
    "changed_paths",
    "child_env",
    "classify_outcome",
    "create_worktree",
    "dry_run_lifecycle",
    "executor_argv",
    "load_leases",
    "provider_status",
    "recover",
    "remove_worktree",
    "role_budget",
    "run_once",
    "run_worker",
    "save_leases",
    "skill_line",
    "verify",
    "worktree_path",
    "worktree_root",
]
