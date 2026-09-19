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
from datetime import UTC, datetime, timedelta
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

PROVIDERS = ("claude", "codex", "openrouter", "auto", "claude-first")

# What the operator's provider choice means for lane selection. Without this
# the setting only changed a status line: routing still walked every policy
# lane in priority order, so choosing `openrouter` kept running Claude.
#
# `claude-first` permits the same lanes as `auto`. The difference is not which
# lanes may run but what happens when the subscription allowance runs out
# mid-task: see `failover_on_exhaustion`.
#
# `codex_local` joined both on 2026-09-18. It is a separate subscription, so a
# run with only Claude and OpenRouter permitted would leave an entire included
# allowance unused -- and would have no lane at all for frontend work, which
# policy no longer lets Claude write.
PROVIDER_LANES: dict[str, tuple[str, ...]] = {
    "claude": ("claude_subscription",),
    "codex": ("codex_local",),
    "openrouter": ("openrouter",),
    "auto": ("claude_subscription", "codex_local", "openrouter"),
    "claude-first": ("claude_subscription", "codex_local", "openrouter"),
}

CLAUDE_LANE = "claude_subscription"
CODEX_LANE = "codex_local"

# The subscription's rolling allowance window, used when the harness does not
# print an explicit reset instant. Five hours is what Claude meters against and
# what policy already records for the other subscription lane; coming back too
# late costs one delay, coming back too early costs one wasted attempt.
DEFAULT_USAGE_WINDOW_SECONDS = 18000

# How many times one task may change lane because a provider ran out. It is not
# a retry budget -- no attempt is spent -- but an unbounded loop between two
# exhausted lanes would still spin, so it is bounded by the number of lanes
# there are to move between.
MAX_PROVIDER_FAILOVERS = 3

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
    """Where worker checkouts live: beside the repository, never inside it.

    A mistyped or stale configured path that lands inside the checkout would
    undo the isolation the worktree exists for and let an unattended worker
    edit the coordinator's own tree, so it is refused rather than used.
    """
    configured = str(config.get("worktree_root") or "").strip()
    if not configured:
        return root.parent / f"{root.name.split('-')[0]}-agents"
    path = Path(configured).expanduser()
    try:
        resolved = path.resolve()
        inside = resolved == root.resolve() or root.resolve() in resolved.parents
    except OSError:
        inside = False
    if inside:
        raise ValueError(
            f"worktree_root {resolved} is inside the repository at {root}; "
            "worker checkouts must live outside it"
        )
    return path


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


def head_sha(path: Path, *, runner: Runner | None = None) -> str:
    """The commit a checkout is currently on."""
    result = _git(path, ["rev-parse", "HEAD"], runner=runner)
    return (result.stdout or "").strip() if result.returncode == 0 else ""


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
        return {
            "created": False,
            "path": str(path),
            "branch": branch,
            "base_sha": head_sha(path, runner=runner),
        }

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
    return {
        "created": True,
        "path": str(path),
        "branch": branch,
        "base_sha": head_sha(path, runner=runner),
    }


def remove_worktree(
    root: Path, path: Path, *, runner: Runner | None = None
) -> dict[str, Any]:
    """Remove a worktree. Only ever called for finished or throwaway work."""
    result = _git(root, ["worktree", "remove", "--force", str(path)], runner=runner)
    if result.returncode != 0 and path.exists():
        shutil.rmtree(path, ignore_errors=True)
        _git(root, ["worktree", "prune"], runner=runner)
    return {"removed": not path.exists(), "path": str(path)}


def provider_lanes(config: Mapping[str, Any]) -> tuple[str, ...]:
    """The lanes the operator's provider choice permits."""
    provider = str(config.get("provider") or "claude")
    return PROVIDER_LANES.get(provider, PROVIDER_LANES["claude"])


def lanes_excluded_by_provider(
    policy: Mapping[str, Any], config: Mapping[str, Any]
) -> dict[str, str]:
    """Lanes the provider selection rules out, with the reason.

    Expressed as exclusions handed to the existing router rather than as a
    second selection step, so priority, fallbacks and rejection messages keep
    working exactly as they did.
    """
    allowed = provider_lanes(config)
    provider = str(config.get("provider") or "claude")
    return {
        name: f"{name}: provider is set to {provider}"
        for name in (policy.get("lanes") or {})
        if name not in allowed
    }


def failover_on_exhaustion(config: Mapping[str, Any]) -> bool:
    """Whether a lane that runs out of allowance may hand the task to another.

    Expressed as "the operator permitted more than one lane" rather than as a
    test for one mode name, so `auto` gets the same behaviour it would obviously
    want and a future mode does not have to be added here as well.
    """
    return len(provider_lanes(config)) > 1


def local_provider_health(paths: localstate.LocalPaths) -> dict[str, str]:
    """Lane health as this machine observed it, cooldowns already expired.

    The tracked ledger under `ops/state` belongs to the cloud loop and is never
    written here, so an exhaustion seen locally is recorded locally. The shape
    is identical, which is why `state.provider_health` reads it unchanged --
    including the rule that a cooldown whose reset has passed is available
    again, which is what makes Claude preferred once more.
    """
    return state.provider_health(localstate.read(paths.providers, {"lanes": {}}))


def merge_local_health(paths: localstate.LocalPaths, ctx: Any) -> dict[str, str]:
    """Fold locally observed health into the context the router will read.

    A merge rather than a replacement: the tracked record also carries the
    privacy confirmation and the lane qualification, and dropping those to
    record a cooldown would make the lane ineligible for the wrong reason.
    """
    observed = localstate.read(paths.providers, {"lanes": {}}).get("lanes", {})
    lanes = ctx.providers.setdefault("lanes", {})
    for lane, record in observed.items():
        lanes.setdefault(lane, {}).update(record)
    return state.provider_health(ctx.providers)


def mark_lane_exhausted(
    paths: localstate.LocalPaths,
    lane: str,
    *,
    policy: Mapping[str, Any] | None = None,
    reset_at: str = "",
    reason: str = "",
) -> dict[str, Any]:
    """Put one lane into cooldown locally because its allowance ran out.

    This is the existing cooldown mechanism, written to the local ledger: the
    same `COOLDOWN` status, the same `reset_at`, and therefore the same
    automatic return to the pool when the window passes. Nothing about the task
    -- its lease, its branch, its worktree, its base commit or its repair
    budget -- is touched, because none of that went wrong.
    """
    lanes = (policy or {}).get("lanes") or {}
    window = int(
        (lanes.get(lane) or {}).get(
            "usage_window_seconds", DEFAULT_USAGE_WINDOW_SECONDS
        )
    )
    if not reset_at:
        reset_at = (datetime.now(UTC) + timedelta(seconds=window)).isoformat(
            timespec="seconds"
        )
    providers = localstate.read(paths.providers, {"lanes": {}})
    state.mark_provider(
        providers,
        lane,
        "COOLDOWN",
        reason=reason or "provider allowance appears exhausted",
        reset_at=reset_at,
    )
    localstate.write(paths.providers, providers)
    localstate.append_event(
        paths,
        "provider_exhausted",
        lane=lane,
        reset_at=reset_at,
        reason=reason,
    )
    return {"lane": lane, "reset_at": reset_at, "reason": reason}


def provider_cooldowns(paths: localstate.LocalPaths) -> dict[str, str]:
    """Each lane still cooling down, and when it comes back."""
    stored = localstate.read(paths.providers, {"lanes": {}}).get("lanes", {})
    health = local_provider_health(paths)
    return {
        lane: str(stored.get(lane, {}).get("reset_at") or "")
        for lane, status in health.items()
        if status == "COOLDOWN"
    }


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
    if provider in ("auto", "claude-first"):
        report = executors.availability()
        usable = [name for name, row in report.items() if row["available"]]
        preference = (
            "Claude while its allowance lasts, then an approved OpenRouter model"
            if provider == "claude-first"
            else "either lane may run"
        )
        return {
            "provider": provider,
            "harness": ", ".join(usable) or "none",
            "status": "AVAILABLE" if usable else "AVAILABLE_LATER",
            "reason": f"{preference}; installed: {', '.join(usable) or 'none'}",
            "lanes": list(provider_lanes(config)),
        }
    executor = executors.for_lane(
        {"openrouter": "openrouter", "codex": CODEX_LANE}.get(
            provider, "claude_subscription"
        )
    )
    ok, reason = executor.available()
    return {
        "provider": provider,
        "harness": executor.name,
        "status": "AVAILABLE" if ok else "AVAILABLE_LATER",
        "reason": reason,
        "lanes": list(provider_lanes(config)),
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
    effort: str = "",
) -> list[str]:
    """The harness command line for this lane, without the prompt."""
    executor = executors.for_lane(lane, effort=effort)
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
    effort: str = "",
    run_id: str | None = None,
    popen: Callable[..., Any] | None = None,
    on_spawn: Callable[[int], None] | None = None,
) -> dict[str, Any]:
    """Run one worker in the harness its lane runs in.

    Which harness is not a new decision: the router already chose the lane, and
    policy already confines each model family to a lane, so the lane says which
    of the three harnesses starts.

    `effort` is the tier the router picked. Only the Codex lane can act on it;
    the others ignore it, which is why it is passed rather than folded into the
    role budget that every harness reads.
    """
    executor = executors.for_lane(lane, effort=effort)
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
    config: Mapping[str, Any] | None = None,
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

    unusable = dict(unavailable_lanes(inputs.policy))
    if config is not None:
        unusable.update(lanes_excluded_by_provider(inputs.policy, config))
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
        # Anything outside the two documented verdicts is unreadable, not a
        # pass. `{}` and a typo both used to sail through as clean reviews.
        verdict = str(parsed.get("verdict") or "").strip().lower()
        if verdict not in ("pass", "changes_requested"):
            return {
                "verdict": "unreadable",
                "summary": f"unrecognised verdict: {verdict or 'missing'}",
                "findings": [f for f in (findings or []) if isinstance(f, dict)],
            }
        return {
            "verdict": verdict,
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


def diff_of(
    root: Path, worktree: Path, *, base: str, runner: Runner | None = None
) -> str:
    """The whole task delta a reviewer must see: every commit plus the rest.

    Reviewing `git diff HEAD` showed nothing once the worker committed, so a
    reviewer could approve an implementation it had never seen.
    """
    committed = _git(worktree, ["diff", f"{base}..HEAD"], runner=runner)
    tracked = _git(worktree, ["diff", "HEAD"], runner=runner)
    untracked = _git(
        worktree, ["ls-files", "--others", "--exclude-standard"], runner=runner
    )
    parts = [committed.stdout or "", tracked.stdout or ""]
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


def merge_base(worktree: Path, *, runner: Runner | None = None) -> str:
    """Where this branch diverged from what it will be merged into."""
    for base in ("origin/main", "main"):
        found = _git(worktree, ["merge-base", "HEAD", base], runner=runner)
        if found.returncode == 0 and (found.stdout or "").strip():
            return (found.stdout or "").strip()
    return ""


def task_baseline(
    paths: localstate.LocalPaths,
    task_id: int,
    *,
    worktree: Path,
    runner: Runner | None = None,
) -> str:
    """The commit this task's branch diverged from.

    Every judgement about what a task changed is a range starting here, so it
    has to survive the worker committing, a repair committing on top, and a
    restart. It used to be a snapshot: whatever HEAD was the first time this
    ran, stored and thereafter only read, on the reasoning that a baseline
    which drifts forward is a governance check that sees less each time.

    That reasoning holds inside one attempt and fails across them. A worktree
    outlives the attempt that created it, so a task picked up again days later
    kept a baseline from before everything that had merged in between -- and
    the governance guard, asked what the branch changed, was shown every
    commit main had gained since. Task 16 was refused for editing
    `ops/policy.json` and `.github/workflows`, neither of which its worker had
    touched.

    So it is derived rather than remembered. The merge base is where this
    branch actually left main: it does not move as the branch commits, it does
    not move as main moves ahead, and it moves forward only when the branch
    genuinely merges main in -- which is exactly when those commits stop being
    this branch's changes. The recorded value is kept as a fallback for a
    checkout git cannot answer for.
    """
    record = localstate.worker_records(paths).get(str(task_id)) or {}
    recorded = str(record.get("base_sha") or "")
    # Ordered by how much each answer knows. The merge base is derived from
    # the branch itself and cannot go stale; a previously recorded value is
    # the next best thing for a checkout git will not answer for; and HEAD is
    # the original behaviour, which is still right for a worktree that has
    # just been created and has no divergence to measure yet.
    base = (
        merge_base(worktree, runner=runner)
        or recorded
        or head_sha(worktree, runner=runner)
    )
    if base and base != recorded:
        localstate.save_worker(paths, str(task_id), {"base_sha": base})
    return base


def read_leases(root: Path, paths: localstate.LocalPaths) -> dict[str, Any]:
    """The lease ledger as it stands, writing nothing.

    `load_leases` seeds the local copy on first use, which is right for a run
    and wrong for a page view: rendering the dashboard created runtime state
    and made a documented read-only endpoint mutate the disk.
    """
    if paths.leases.exists():
        return localstate.read(paths.leases, {"leases": {}})
    tracked = state.read_json(state.Paths(root).tasks, {"leases": {}})
    return {"leases": tracked.get("leases", {})}


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


def save_leases(
    paths: localstate.LocalPaths,
    tasks: dict[str, Any],
    *,
    task_id: int | None = None,
) -> None:
    """Persist the lease ledger, without discarding anyone else's entry.

    `tasks` is one worker's in-memory snapshot, taken when that worker started.
    Writing the whole of it back was correct while one writer existed and is a
    data-loss bug now: a worker that began before its neighbour acquired a
    lease has never seen that lease, so writing its snapshot deletes it. The
    neighbour then holds a branch the ledger says nobody holds, the writer cap
    counts one worker short, and the next coordinator hands the same task out
    again -- two writers on one branch, which is the failure the lease exists
    to prevent.

    So a caller that changed one task says which, and only that entry is
    merged into whatever is on disk now. A caller that legitimately owns the
    whole document -- the reclaim sweep, or the claim path, both of which hold
    the schedule lock while they read it -- passes nothing and writes it whole.
    Either way the read and the write happen under one lock.
    """
    if task_id is None:
        localstate.mutate(paths, paths.leases, lambda stored: stored.update(tasks))
        return

    key = str(task_id)
    mine = (tasks.get("leases") or {}).get(key)

    def change(stored: dict[str, Any]) -> None:
        leases_on_disk = stored.setdefault("leases", {})
        if mine is None:
            leases_on_disk.pop(key, None)
        else:
            leases_on_disk[key] = mine

    localstate.mutate(paths, paths.leases, change, {"leases": {}})


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
    committed = _git(worktree, ["diff", "--name-only", f"{base}..HEAD"], runner=runner)
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
    # The worktree has no `.tools` of its own -- it is machine-local and
    # untracked -- so the script cannot find the pinned uv by relative path.
    # It reads this override, which is the same one `agentops-local.ps1` takes.
    child_env = {**os.environ, "SHOULDER_UV_PATH": str(binary)}
    if kind == "fast":
        commands = toolchain.fast_check_commands(binary)
    elif kind == "gated":
        # The worktree's own copy of the script, not the main checkout's.
        # `check.ps1` moves to the parent of its own location, so running the
        # repository copy verified the coordinator's tree instead of the
        # branch under test -- and could write to it.
        commands = [
            ["pwsh", "-NoProfile", "-File", str(worktree / "scripts" / "check.ps1")]
        ]
    else:
        raise ValueError(f"unknown verification kind: {kind}")

    if not any(toolchain.needs_infra_lock(command) for command in commands):
        result = toolchain.run_commands(
            worktree, commands, runner=runner, env=child_env
        )
        localstate.append_event(paths, "verification", kind=kind, ok=result["ok"])
        return {**result, "kind": kind, "locked": False}

    with toolchain.infra_lock(paths, owner=owner):
        result = toolchain.run_commands(
            worktree, commands, runner=runner, env=child_env
        )
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

# Work that verified but was never reviewed. It is deliberately not
# `ready_for_pr`: skipping review is a diagnostic, and a diagnostic must not
# produce something that looks like reviewed production work.
UNREVIEWED = "verification_complete_unreviewed"

# The outcome for a task nothing was wrong with, which stopped because the
# provider had nothing left to give. It is deliberately not `blocked`.
WAITING_PROVIDER = "waiting_provider"

# A task nobody may pick up again locally. `ready_for_pr` is finished as far as
# this runtime is concerned and waits for a pull request to be merged; the
# unreviewed state is a diagnostic result, not work to redo blindly.
NON_DISPATCHABLE_STATES = ("ready_for_pr", UNREVIEWED)


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
    if outcome in ("completed", "ready_for_pr", UNREVIEWED):
        # The lease records what actually happened. An unreviewed run parks in
        # its own state so nothing downstream can mistake it for reviewed work.
        state_name = "ready_for_pr" if outcome != UNREVIEWED else UNREVIEWED
        lease["state"] = state_name
        lease["heartbeat_at"] = localstate.now()
        save_leases(paths, tasks, task_id=task_id)
        return {"lease_state": state_name, "escalated": False}

    if outcome == WAITING_PROVIDER:
        # Not terminal. Releasing this as `blocked` stranded the task: the
        # coordinator refuses a blocked lease until a human clears it, so a
        # task parked for one usage window never came back and its worktree
        # sat there forever.
        leases.park(tasks, task_id, reason="provider allowance exhausted")
        save_leases(paths, tasks, task_id=task_id)
        return {"lease_state": leases.WAITING_PROVIDER, "escalated": False}

    if outcome in ("governance_refused", "blocked"):
        leases.release(tasks, task_id, "blocked")
        save_leases(paths, tasks, task_id=task_id)
        return {"lease_state": "blocked", "escalated": False}

    if outcome in REPAIRABLE:
        try:
            leases.begin_repair(
                tasks, dict(policy), task_id, reason="ci", once_key=once_key
            )
            save_leases(paths, tasks, task_id=task_id)
            return {"lease_state": "repairing", "escalated": True}
        except leases.RepairBudgetExhausted as exhausted:
            leases.release(tasks, task_id, "blocked")
            save_leases(paths, tasks, task_id=task_id)
            return {
                "lease_state": "blocked",
                "escalated": False,
                "reason": str(exhausted),
            }

    save_leases(paths, tasks, task_id=task_id)
    return {"lease_state": lease.get("state"), "escalated": False}


def _record(paths: localstate.LocalPaths, task_id: int, /, **fields: Any) -> None:
    """Update this task's worker record.

    `task_id` is positional-only so a caller may also record a field of
    its own called `task_id` without colliding with this parameter.
    """
    localstate.save_worker(paths, str(task_id), fields)


def implement_once(
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
    tasks: dict[str, Any] | None = None,
) -> dict[str, Any]:
    def on_spawn(pid: int, lane: str) -> None:
        image = worker_image(lane)
        _record(paths, task_id, pid=pid, image=image)
        # The lease needs it too: the stale-lease check asks whether the
        # previous owner is still running, and a lease with no pid answers
        # "gone" for a worker that is very much alive.
        if tasks is not None:
            lease = (tasks.get("leases") or {}).get(str(task_id))
            if lease is not None:
                lease["pid"] = pid
                lease["image"] = image
                save_leases(paths, tasks, task_id=task_id)

    run = run_worker(
        root,
        paths,
        prompt=prompt,
        model=assignment.harness_model,
        role=role,
        worktree=worktree,
        config=config,
        lane=assignment.lane,
        effort=getattr(assignment, "effort", ""),
        popen=popen,
        on_spawn=lambda pid: on_spawn(pid, assignment.lane),
    )
    _record(
        paths,
        task_id,
        model=assignment.harness_model,
        lane=assignment.lane,
        # Recorded because on one lane it is applied rather than advisory:
        # `codex exec -c model_reasoning_effort` really does set it, so a
        # dashboard that omitted it would hide half of what was chosen.
        effort=getattr(assignment, "effort", ""),
        capability_class=getattr(assignment, "capability_class", ""),
        harness=run.get("harness"),
        provider=run.get("provider"),
        usage=run.get("usage"),
        cost_usd=run.get("cost_usd"),
        cost_known=run.get("cost_known"),
        last_action=run.get("last_action"),
    )
    return run


def implement_with_failover(
    root: Path,
    paths: localstate.LocalPaths,
    *,
    task_id: int,
    assignment: Any,
    worktree: Path,
    config: Mapping[str, Any],
    policy: Mapping[str, Any],
    prompt: str,
    role: str,
    popen: Callable[..., Any] | None,
    tasks: dict[str, Any] | None,
    replan: Callable[[frozenset[str]], Any | None],
) -> dict[str, Any]:
    """Run the writer, changing lane if the provider's allowance runs out.

    Exhaustion is not implementation failure and is deliberately not returned
    as one: it never reaches `classify_outcome`, so it spends no implementation
    attempt and no repair cycle. The task keeps its lease, its branch, its
    worktree, its uncommitted edits and its recorded base commit, because none
    of those is what went wrong -- only the account that was paying.

    The lane that ran out is put into cooldown first, so the re-plan that
    follows is made by the existing router against the existing health rules
    rather than by a second selection path invented here.
    """
    failovers: list[dict[str, Any]] = []
    excluded: set[str] = set()
    while True:
        run = implement_once(
            root,
            paths,
            task_id=task_id,
            assignment=assignment,
            worktree=worktree,
            config=config,
            prompt=prompt,
            role=role,
            popen=popen,
            tasks=tasks,
        )
        spent = executors.exhaustion(run)
        if spent is None:
            return {
                "run": run,
                "assignment": assignment,
                "failovers": failovers,
                "blocked": "",
            }

        cooldown = mark_lane_exhausted(
            paths,
            assignment.lane,
            policy=policy,
            reset_at=str(spent.get("reset_at") or ""),
            reason=f"the harness reported: {spent['marker']}",
        )
        excluded.add(assignment.lane)
        _record(paths, task_id, provider_cooldown=cooldown)

        blocked = ""
        replacement = None
        if not failover_on_exhaustion(config):
            blocked = (
                f"BLOCKED_WAITING_PROVIDER: {assignment.lane} is out of allowance "
                f"until {cooldown['reset_at']} and the provider setting permits "
                "no other lane"
            )
        elif len(failovers) >= MAX_PROVIDER_FAILOVERS:
            blocked = (
                "BLOCKED_WAITING_PROVIDER: every permitted lane ran out of "
                f"allowance; {assignment.lane} returns at {cooldown['reset_at']}"
            )
        else:
            replacement = replan(frozenset(excluded))
            if replacement is None:
                blocked = (
                    f"BLOCKED_WAITING_PROVIDER: {assignment.lane} is out of "
                    f"allowance until {cooldown['reset_at']} and no approved "
                    "fallback lane can take this task"
                )
        if blocked or replacement is None:
            return {
                "run": run,
                "assignment": assignment,
                "failovers": failovers,
                "blocked": blocked,
            }

        transition = {
            "at": localstate.now(),
            "task_id": task_id,
            "reason": "provider_exhausted",
            "previous_lane": assignment.lane,
            "previous_model": assignment.harness_model,
            "reset_at": cooldown["reset_at"],
            "next_lane": replacement.lane,
            "next_model": replacement.harness_model,
            "harness": executors.for_lane(replacement.lane).name,
        }
        failovers.append(transition)
        localstate.append_event(paths, "provider_failover", **transition)
        assignment = replacement


def reclaim_abandoned(
    paths: localstate.LocalPaths, tasks: dict[str, Any], policy: Mapping[str, Any]
) -> list[int]:
    """Stop an active lease from pretending its dead owner is still working.

    A run that ends mid-repair leaves the lease `repairing`, which is active,
    so the coordinator skips the task until the lease finally goes stale --
    fifteen minutes of a task nobody is working on and nobody may pick up. If
    the recorded owner is provably gone, its last heartbeat is backdated so the
    existing staleness path reclaims it on this run rather than the next hour's.
    """
    reclaimed: list[int] = []
    for key, lease in (tasks.get("leases") or {}).items():
        if lease.get("state") not in leases.ACTIVE_STATES:
            continue
        if leases.is_stale(lease, dict(policy)):
            continue
        pid = lease.get("pid")
        if pid is None or localstate.process_alive(int(pid), lease.get("image")):
            continue
        missed = int(policy["lease"]["stale_after_missed_heartbeats"]) + 1
        gap = missed * int(policy["lease"]["heartbeat_seconds"])
        lease["heartbeat_at"] = (datetime.now(UTC) - timedelta(seconds=gap)).isoformat(
            timespec="seconds"
        )
        lease["reclaimed_from"] = {"pid": pid, "at": localstate.now()}
        reclaimed.append(int(key))
    if reclaimed:
        # One entry at a time, because this sweep runs outside the schedule
        # lock as well as inside it. Writing the whole ledger from a snapshot
        # taken before the sweep began would delete any lease acquired since
        # -- reclaiming an abandoned worker by abandoning a live one.
        for reclaimed_id in reclaimed:
            save_leases(paths, tasks, task_id=reclaimed_id)
        localstate.append_event(paths, "leases_reclaimed", tasks=reclaimed)
    return reclaimed


def settled_locally(tasks: Mapping[str, Any], task_id: int) -> str:
    """The non-dispatchable state this task is already in, if any.

    Read from the local ledger rather than by changing the shared lease states,
    because the cloud loop's notion of active and terminal is not this
    runtime's to redefine.
    """
    lease = (tasks.get("leases") or {}).get(str(task_id)) or {}
    state_name = str(lease.get("state") or "")
    return state_name if state_name in NON_DISPATCHABLE_STATES else ""


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
    # A lane this machine saw run out of allowance is in cooldown here even
    # though the tracked ledger knows nothing about it, so the router sees the
    # cooldown and prefers whatever is still available.
    merge_local_health(paths, ctx)
    reclaim_abandoned(paths, ctx.tasks, ctx.policy)
    store = approvals.load(paths)
    owner = owner or f"local-{os.getpid()}"

    candidate = coordinator.next_eligible(ctx)
    if candidate is None:
        return {"dispatched": False, "reason": "no eligible task"}

    # `ready_for_pr` is neither an active lease nor a terminal one, so the
    # coordinator offers the task again and a second worker starts on work that
    # is already finished and waiting for a pull request.
    settled = settled_locally(ctx.tasks, candidate.task.id)
    if settled:
        waiting = (
            "it is waiting for its pull request"
            if settled == "ready_for_pr"
            else "it verified without review and is not eligible for a pull request"
        )
        return {
            "dispatched": False,
            "task_id": candidate.task.id,
            "reason": (
                f"task {candidate.task.id} is {settled} locally; "
                f"{waiting}, not for another worker"
            ),
        }

    plan = local_plan(ctx, candidate, store, config=config)
    if plan.writer is None or plan.blocked_reason:
        return {
            "dispatched": False,
            "reason": plan.blocked_reason or "no writer could be routed",
            "rejections": plan.rejections,
        }

    run_id = uuid.uuid4().hex[:12]
    try:
        # Read, claim and write under one cross-process lock. Two coordinators
        # could otherwise each read no lease, each pass the writer cap against
        # its own stale snapshot, and each start a worker on the same branch.
        # It is held for the decision only, never for the work.
        with toolchain.schedule_lock(paths, owner=owner):
            ctx.tasks = load_leases(root, paths)
            reclaim_abandoned(paths, ctx.tasks, ctx.policy)
            settled_now = settled_locally(ctx.tasks, candidate.task.id)
            if settled_now:
                return {
                    "dispatched": False,
                    "task_id": candidate.task.id,
                    "reason": f"task {candidate.task.id} is {settled_now} locally",
                }
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
            save_leases(paths, ctx.tasks)
    except toolchain.LockBusy as busy:
        return {
            "dispatched": False,
            "reason": f"another coordinator is deciding: {busy}",
        }
    except leases.LeaseConflict as conflict:
        return {"dispatched": False, "reason": str(conflict)}
    except leases.AttemptsExhausted as exhausted:
        leases.release(ctx.tasks, candidate.task.id, "blocked")
        save_leases(paths, ctx.tasks, task_id=candidate.task.id)
        return {"dispatched": False, "reason": f"BLOCKED_AUTOMATION: {exhausted}"}

    task_id = candidate.task.id
    worktree = worktree_path(root, config, plan.branch)
    created = create_worktree(root, plan.branch, worktree, runner=runner)
    # Captured before the worker touches anything, and reused on every later
    # pass over this task.
    base_sha = task_baseline(paths, task_id, worktree=worktree, runner=runner) or str(
        created.get("base_sha") or ""
    )
    _record(
        paths,
        task_id,
        task_id=task_id,
        base_sha=base_sha,
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
    failovers: list[dict[str, Any]] = []
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
            provider_failovers=failovers,
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
            "provider_failovers": failovers,
            "run": run,
            "review": verdict,
            "verification": verification,
            "outcome": final,
            "detail": detail,
            **result,
        }

    def replan(exclude: frozenset[str]) -> Any | None:
        """A writer for this same task, avoiding the lanes that ran out.

        The cooldown is already recorded when this is called, so the answer
        comes from the existing router reading the existing health rules; the
        explicit exclusion only makes the intent legible in the rejections.
        """
        merge_local_health(paths, ctx)
        replacement = local_plan(
            ctx, candidate, store, exclude_lanes=exclude, config=config
        )
        return replacement.writer

    def implement(prompt_text: str) -> dict[str, Any]:
        return implement_with_failover(
            root,
            paths,
            task_id=task_id,
            assignment=writer,
            worktree=worktree,
            config=config,
            policy=ctx.policy,
            prompt=prompt_text,
            role="implement",
            popen=popen,
            tasks=ctx.tasks,
            replan=replan,
        )

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
                config=config,
            )
            if escalated.writer is None:
                # Rerunning the assignment that just failed, or one from the
                # lane being excluded, is not an escalation.
                return finish(
                    "blocked",
                    escalated.blocked_reason or "no lane left to escalate to",
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
        attempted = implement(prompt)
        run = attempted["run"]
        writer = attempted["assignment"]
        failovers.extend(attempted["failovers"])
        phases.append({"phase": "implementing", "outcome": run["outcome"]})
        if attempted["blocked"]:
            # The work is intact in the worktree and the task keeps its branch,
            # its base commit and its attempt. Nothing is retried, because a
            # retry cannot make an allowance refill sooner, and the lease is
            # parked rather than blocked so the task comes back by itself.
            return finish(WAITING_PROVIDER, attempted["blocked"])

        changed = changed_paths(root, worktree, base=base_sha, runner=runner)
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
            diff = diff_of(root, worktree, base=base_sha, runner=runner)
            review_run = run_worker(
                root,
                paths,
                prompt=review_prompt(root, task_id, diff, changed),
                model=plan.reviewer.harness_model,
                role="review",
                worktree=worktree,
                config=config,
                lane=plan.reviewer.lane,
                effort=getattr(plan.reviewer, "effort", ""),
                popen=popen,
            )
            if not review_run.get("ok"):
                # A reviewer that exited non-zero may still have printed
                # something pass-shaped. Reading it as a verdict would let a
                # crashed review mark the task ready.
                return finish(
                    "blocked",
                    f"the reviewer did not complete: {review_run.get('outcome')}",
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
                save_leases(paths, ctx.tasks, task_id=task_id)
            except leases.RepairBudgetExhausted as exhausted:
                return finish("blocked", str(exhausted))

            _record(paths, task_id, phase="repairing")
            repaired = implement(repair_prompt(root, task_id, must_fix))
            run = repaired["run"]
            writer = repaired["assignment"]
            failovers.extend(repaired["failovers"])
            phases.append({"phase": "repairing", "outcome": run["outcome"]})
            if repaired["blocked"]:
                return finish(WAITING_PROVIDER, repaired["blocked"])

            changed = changed_paths(root, worktree, base=base_sha, runner=runner)
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

    changed = changed_paths(root, worktree, base=base_sha, runner=runner)
    violations = governance.violations(changed)
    if violations:
        return finish("governance_refused", ", ".join(violations))

    _record(paths, task_id, changed_files=changed)
    if not review or plan.reviewer is None:
        # Verified, but nobody looked at it. Saying `ready_for_pr` here would
        # make a diagnostic run indistinguishable from reviewed work.
        return finish(
            UNREVIEWED,
            "review was skipped; this is not eligible for a pull request",
        )
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
    created = create_worktree(root, branch, worktree, runner=runner)
    base_sha = str(created.get("base_sha") or "")
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
    changed = changed_paths(root, worktree, base=base_sha, runner=runner)
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
                "base_sha": record.get("base_sha", ""),
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
    base_sha = str(created.get("base_sha") or "")

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
    changed = changed_paths(root, worktree, base=base_sha, runner=runner)
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
    "CLAUDE_LANE",
    "CLAUDE_BINARY",
    "OPENROUTER_BASE_URL",
    "OPENROUTER_KEY_ENV",
    "PROVIDERS",
    "build_prompt",
    "changed_paths",
    "diff_of",
    "head_sha",
    "child_env",
    "classify_outcome",
    "create_worktree",
    "dry_run_lifecycle",
    "executor_argv",
    "failover_on_exhaustion",
    "implement_once",
    "implement_with_failover",
    "local_provider_health",
    "mark_lane_exhausted",
    "merge_local_health",
    "provider_cooldowns",
    "load_leases",
    "read_leases",
    "reclaim_abandoned",
    "provider_lanes",
    "provider_status",
    "recover",
    "remove_worktree",
    "role_budget",
    "run_once",
    "settled_locally",
    "task_baseline",
    "run_worker",
    "save_leases",
    "skill_line",
    "verify",
    "WAITING_PROVIDER",
    "worktree_path",
    "worktree_root",
]
