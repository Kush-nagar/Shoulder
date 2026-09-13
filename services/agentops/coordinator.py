"""The coordinator: what to work on next, and who should do it.

It owns backlog parsing, dependency evaluation, classification, routing, and
lease allocation. It never implements a task itself, and it never invents one:
every candidate comes from `docs/06-tasks.md`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import backlog as backlog_mod
from . import catalog, classify, leases, routing, state


@dataclass
class Context:
    root: Path
    paths: state.Paths
    policy: dict[str, Any]
    backlog: backlog_mod.Backlog
    progress: dict[str, Any]
    models_state: dict[str, Any]
    providers: dict[str, Any]
    budget: dict[str, Any]
    tasks: dict[str, Any]

    def routing_inputs(self) -> routing.RoutingInputs:
        models = catalog.models_from_state(self.models_state)
        # Account-level privacy confirmations are recorded per lane in provider
        # state, so fold them into the policy the router sees.
        policy = dict(self.policy)
        policy["lanes"] = {
            name: {
                **lane,
                "privacy_confirmed": bool(
                    self.providers.get("lanes", {})
                    .get(name, {})
                    .get("privacy_confirmed")
                ),
            }
            for name, lane in self.policy["lanes"].items()
        }
        qualification = {
            model_id: record.get("qualification", "CANDIDATE")
            for model_id, record in self.models_state.get("models", {}).items()
        }
        return routing.RoutingInputs(
            policy=policy,
            models=models,
            qualification=qualification,
            provider_health=state.provider_health(self.providers),
            budget_blocked=state.budget_blocked(self.policy, self.budget),
            qualified_lanes=state.qualified_lanes(self.providers),
        )


def load_context(root: Path) -> Context:
    paths = state.Paths(root)
    return Context(
        root=root,
        paths=paths,
        policy=state.load_policy(paths),
        backlog=backlog_mod.load(root),
        progress=state.read_json(paths.progress, {"completed_tasks": [], "gates": {}}),
        models_state=state.read_json(paths.models, {"models": {}}),
        providers=state.read_json(paths.providers, {"lanes": {}}),
        budget=state.read_json(paths.budget, {"spend": {}}),
        tasks=state.read_json(paths.tasks, {"leases": {}}),
    )


@dataclass
class Candidate:
    task: backlog_mod.Task
    block: backlog_mod.Block | None
    eligible: bool
    missing_prerequisites: list[int] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def evaluate(ctx: Context, task: backlog_mod.Task) -> Candidate:
    """Decide whether one task may be started right now."""
    block = ctx.backlog.block_for_task(task.id)
    done = state.completed_tasks(ctx.progress)
    reasons: list[str] = []

    if task.id in done:
        return Candidate(task, block, False, [], ["already complete"])

    # A task someone is already working on is not a candidate. Without this,
    # planning and dispatch disagree and the lease conflict is what surfaces
    # the problem, one step too late.
    for lease in leases.active_leases(ctx.tasks, ctx.policy):
        if int(lease.get("task_id", -1)) == task.id:
            return Candidate(
                task,
                block,
                False,
                [],
                [f"already leased by {lease.get('owner')}"],
            )

    satisfied, missing = state.dependencies_satisfied(ctx.progress, task.prerequisites)
    if not satisfied:
        reasons.append(f"prerequisites not complete: {missing}")

    if task.gated and not state.gate_passed(ctx.progress):
        reasons.append("mandatory real-use gate has not passed")

    if state.task_budget_exceeded(ctx.policy, ctx.budget, task.id):
        spent = state.task_spend(ctx.budget, task.id)
        ceiling = ctx.policy["budget"]["per_task_usd"]
        reasons.append(f"per-task budget exhausted: ${spent} of ${ceiling}")

    # Phase D and later contain the machine-learning work that AGENTS.md rule 5
    # forbids before the gate. The coordinator never starts them on its own.
    phase = task.phase
    late_phase = any(p in phase for p in ("Phase D", "Phase E", "Phase F"))
    if late_phase and not ctx.policy["autonomy"]["allow_phase_d_and_later"]:
        reasons.append(f"{phase} is not enabled for autonomous execution")

    # A block may not start before the blocks it depends on are finished.
    if block is not None:
        for other in ctx.backlog.blocks.values():
            if other.id >= block.id:
                continue
            if f"{other.id:02d}" in block.depends_on and not set(other.tasks) <= done:
                reasons.append(f"block {block.slug} depends on unfinished {other.slug}")

    return Candidate(task, block, not reasons, missing, reasons)


def candidates(ctx: Context) -> list[Candidate]:
    return [evaluate(ctx, ctx.backlog.tasks[i]) for i in ctx.backlog.task_ids()]


def next_eligible(ctx: Context) -> Candidate | None:
    """The lowest-numbered task that may legitimately start now."""
    for candidate in candidates(ctx):
        if candidate.eligible:
            return candidate
    return None


@dataclass
class Plan:
    candidate: Candidate
    classification: classify.Classification
    writer: routing.Assignment | None
    reviewer: routing.Assignment | None
    branch: str
    blocked_reason: str | None = None
    rejections: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.candidate.task.id,
            "task_title": self.candidate.task.title,
            "phase": self.candidate.task.phase,
            "block": self.candidate.block.slug if self.candidate.block else None,
            "prerequisites": list(self.candidate.task.prerequisites),
            "branch": self.branch,
            "classification": self.classification.as_dict(),
            "writer": self.writer.as_dict() if self.writer else None,
            "reviewer": self.reviewer.as_dict() if self.reviewer else None,
            "blocked_reason": self.blocked_reason,
            "rejections": self.rejections,
            "verification": self.candidate.task.test,
            "context7_expected": self.classification.context7_expected,
        }


def branch_name(task: backlog_mod.Task, block: backlog_mod.Block | None) -> str:
    prefix = block.slug if block else "task"
    slug = "".join(c if c.isalnum() else "-" for c in task.title.lower())
    slug = "-".join(part for part in slug.split("-") if part)[:40].strip("-")
    return f"{prefix}-t{task.id}-{slug}"


def plan(ctx: Context, candidate: Candidate, *, prior_failures: int = 0) -> Plan:
    classification = classify.classify(candidate.task, prior_failures=prior_failures)
    inputs = ctx.routing_inputs()
    branch = branch_name(candidate.task, candidate.block)

    try:
        writer = routing.select(inputs, classification)
    except routing.RoutingBlocked as blocked:
        return Plan(
            candidate,
            classification,
            None,
            None,
            branch,
            blocked_reason=blocked.reason,
            rejections=blocked.rejections,
        )

    try:
        reviewer: routing.Assignment | None = routing.select_reviewer(
            inputs, classification, writer
        )
    except routing.RoutingBlocked as blocked:
        # A writer with no independent reviewer is not a reason to skip review;
        # it is a reason to stop and say so.
        return Plan(
            candidate,
            classification,
            writer,
            None,
            branch,
            blocked_reason=f"no independent reviewer available: {blocked.reason}",
            rejections=blocked.rejections,
        )

    return Plan(
        candidate,
        classification,
        writer,
        reviewer,
        branch,
        rejections=list(writer.rejections),
    )


def dry_run(root: Path) -> dict[str, Any]:
    """Full read-only selection, exactly as a real dispatch would decide."""
    ctx = load_context(root)
    candidate = next_eligible(ctx)
    if candidate is None:
        blocked = [
            {"task": c.task.id, "title": c.task.title, "reasons": c.reasons}
            for c in candidates(ctx)
            if not c.eligible and "already complete" not in c.reasons
        ]
        return {
            "autonomy_enabled": state.autonomy_enabled(ctx.policy),
            "next_task": None,
            "reason": "no eligible task",
            "blocked": blocked[:5],
        }

    result = plan(ctx, candidate).as_dict()
    result["autonomy_enabled"] = state.autonomy_enabled(ctx.policy)
    result["active_leases"] = [
        {"task_id": lease.get("task_id"), "owner": lease.get("owner")}
        for lease in leases.active_leases(ctx.tasks, ctx.policy)
    ]
    return result
