"""Command line entry point.

Every command is safe to run by hand. Only `dispatch` starts real work, and it
refuses while autonomy is disabled.

    python -m services.agentops.cli status
    python -m services.agentops.cli plan
    python -m services.agentops.cli discover
    python -m services.agentops.cli qualify --lane openrouter
    python -m services.agentops.cli health
    python -m services.agentops.cli dispatch
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from . import catalog, classify, coordinator, leases, notify, qualify, routing, state


def _root(args: argparse.Namespace) -> Path:
    return Path(args.root).resolve()


def _emit(payload: dict[str, Any]) -> int:
    print(json.dumps(payload, indent=2, default=str))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    ctx = coordinator.load_context(_root(args))
    done = state.completed_tasks(ctx.progress)
    return _emit(
        {
            "autonomy_enabled": state.autonomy_enabled(ctx.policy),
            "completed_tasks": sorted(done),
            "remaining_tasks": [t for t in ctx.backlog.task_ids() if t not in done],
            "gates": ctx.progress.get("gates", {}),
            "provider_health": state.provider_health(ctx.providers),
            "budget_blocked": sorted(state.budget_blocked(ctx.policy, ctx.budget)),
            "qualified_models": sorted(
                model_id
                for model_id, record in ctx.models_state.get("models", {}).items()
                if record.get("qualification") == "QUALIFIED"
            ),
            "active_leases": leases.active_leases(ctx.tasks, ctx.policy),
        }
    )


def cmd_plan(args: argparse.Namespace) -> int:
    return _emit(coordinator.dry_run(_root(args)))


def cmd_discover(args: argparse.Namespace) -> int:
    root = _root(args)
    paths = state.Paths(root)
    models, reason = catalog.discover(
        lanes=catalog.namespace_lanes(state.load_policy(paths))
    )
    if not models:
        return _emit({"ok": False, "reason": reason})
    previous = catalog.load_state(paths.models)
    merged = catalog.merge_qualification(models, previous)
    catalog.save_state(paths.models, merged)
    counts: dict[str, int] = {}
    for record in merged["models"].values():
        key = str(record.get("qualification", "CANDIDATE"))
        counts[key] = counts.get(key, 0) + 1
    return _emit({"ok": True, "discovered": len(models), "by_qualification": counts})


def cmd_qualify(args: argparse.Namespace) -> int:
    root = _root(args)
    paths = state.Paths(root)
    policy = state.load_policy(paths)
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        return _emit({"ok": False, "reason": "OPENROUTER_API_KEY is not set"})

    models_state = catalog.load_state(paths.models)
    targets: list[str] = list(args.model or [])
    if not targets:
        # Qualify what routing would actually reach for: candidates that clear
        # a real capability class, cheapest first. Taking whatever the
        # catalogue happens to list first spends the budget proving nothing
        # about the models the router would pick.
        spec = policy["capability_classes"][args.against]
        eligible = [
            (record.get("input_usd_per_mtok", 0.0), model_id)
            for model_id, record in models_state.get("models", {}).items()
            if record.get("qualification") == "CANDIDATE"
            and not record.get("absent")
            and not record.get("deprecated")
            and (args.lane is None or record.get("lane") == args.lane)
            and record.get("supports_tools")
            and record.get("input_usd_per_mtok", -1) >= 0
            and record.get("output_usd_per_mtok", -1) >= 0
            and record.get("context_length", 0) >= spec["min_context"]
            and record.get("input_usd_per_mtok", 1e9) <= spec["max_input_usd_per_mtok"]
            and (not spec["needs_reasoning"] or record.get("supports_reasoning"))
            and (not spec["needs_vision"] or record.get("supports_vision"))
        ]
        targets = [model_id for _, model_id in sorted(eligible)][: args.limit]

    results = []
    for model_id in targets:
        result = qualify.qualify_model(api_key, model_id, policy)
        record = models_state.setdefault("models", {}).setdefault(model_id, {})
        record["qualification"] = result["qualification"]
        record["qualification_evidence"] = {
            k: v for k, v in result.items() if k != "probes"
        }
        record["qualification_probes"] = result["probes"]
        results.append(
            {
                "model": model_id,
                "verdict": result["qualification"],
                "passed": f"{result['passed']}/{result['total']}",
                "cost_usd": result["cost_usd"],
            }
        )
    catalog.save_state(paths.models, models_state)
    return _emit({"ok": True, "results": results})


def cmd_health(args: argparse.Namespace) -> int:
    """Read lane health, or set it explicitly.

    With --probe, a lane is promoted only when its secret is actually present
    in the environment. Without this the seeded UNAVAILABLE state would never
    lift and routing would reject every lane forever.
    """
    root = _root(args)
    paths = state.Paths(root)
    policy = state.load_policy(paths)
    providers = state.read_json(paths.providers, {"lanes": {}})
    changed = False

    if args.probe:
        health = state.provider_health(providers)
        for lane_name, lane in policy["lanes"].items():
            if args.lane and lane_name != args.lane:
                continue
            if not lane.get("enabled", True):
                state.mark_provider(
                    providers,
                    lane_name,
                    "DISABLED",
                    reason="lane is disabled in policy",
                )
                changed = True
                continue

            secret = lane.get("secret")
            if not secret:
                # A secretless lane is subscription-backed and reached through
                # an account-level integration rather than a credential this
                # repository holds -- Codex Cloud through the GitHub app. There
                # is nothing here to probe, so an existing cooldown is the only
                # thing that may keep it out of the pool.
                if health.get(lane_name) == "COOLDOWN":
                    continue
                state.mark_provider(
                    providers,
                    lane_name,
                    "AVAILABLE",
                    reason="subscription lane; availability is proven by use",
                )
            elif os.environ.get(secret):
                state.mark_provider(
                    providers,
                    lane_name,
                    "AVAILABLE",
                    reason=f"{secret} is configured",
                )
            else:
                state.mark_provider(
                    providers,
                    lane_name,
                    "UNAVAILABLE",
                    reason=f"{secret} is not configured",
                )
            changed = True
    elif args.lane:
        state.mark_provider(
            providers,
            args.lane,
            args.status,
            reason=args.reason or "",
            reset_at=args.reset_at,
        )
        changed = True

    if changed:
        state.write_json(paths.providers, providers)
    return _emit({"provider_health": state.provider_health(providers)})


def cmd_qualify_lane(args: argparse.Namespace) -> int:
    """Record that a lane has been proven end to end.

    For a lane whose model cannot be selected -- Codex Cloud, reached by
    mentioning @codex -- qualifying one model proves nothing about what the
    account actually runs. What can be proven is the lane: a real task went
    through it and came back as work on a branch. That proof is recorded here
    and is what routing requires before such a lane takes real work.
    """
    root = _root(args)
    paths = state.Paths(root)
    providers = state.read_json(paths.providers, {"lanes": {}})
    state.mark_lane_qualified(providers, args.lane, evidence=args.evidence)
    state.write_json(paths.providers, providers)
    return _emit(
        {
            "ok": True,
            "lane": args.lane,
            "qualified_lanes": sorted(state.qualified_lanes(providers)),
        }
    )


def cmd_exhausted(args: argparse.Namespace) -> int:
    """Put a subscription lane into cooldown until its allowance resets.

    Codex meters a rolling window and exposes no usage API on consumer plans,
    so exhaustion is inferred from a run that could not proceed. The cooldown
    is the lane's own declared window, which is conservative: coming back too
    early only wastes a retry, coming back too late only delays one.
    """
    from datetime import UTC, datetime, timedelta

    root = _root(args)
    paths = state.Paths(root)
    policy = state.load_policy(paths)
    lane = policy["lanes"].get(args.lane)
    if lane is None:
        _emit({"ok": False, "reason": f"lane {args.lane!r} is not defined"})
        return 1

    window = int(args.window or lane.get("usage_window_seconds", 18000))
    reset_at = (datetime.now(UTC) + timedelta(seconds=window)).isoformat(
        timespec="seconds"
    )
    providers = state.read_json(paths.providers, {"lanes": {}})
    state.mark_provider(
        providers,
        args.lane,
        "COOLDOWN",
        reason=args.reason or "usage allowance appears exhausted",
        reset_at=reset_at,
    )
    state.write_json(paths.providers, providers)
    return _emit(
        {
            "ok": True,
            "lane": args.lane,
            "reset_at": reset_at,
            "provider_health": state.provider_health(providers),
        }
    )


def cmd_spend(args: argparse.Namespace) -> int:
    """Record API spend against a lane and, when given, a task."""
    root = _root(args)
    paths = state.Paths(root)
    policy = state.load_policy(paths)
    budget = state.read_json(paths.budget, {"spend": {}})
    state.record_spend(budget, args.lane, args.usd, task_id=args.task)
    state.write_json(paths.budget, budget)
    return _emit(
        {
            "lane": args.lane,
            "recorded_usd": args.usd,
            "task_total_usd": state.task_spend(budget, args.task)
            if args.task
            else None,
            "budget_blocked": sorted(state.budget_blocked(policy, budget)),
            "task_budget_exceeded": (
                state.task_budget_exceeded(policy, budget, args.task)
                if args.task
                else False
            ),
        }
    )


def cmd_reviewer(args: argparse.Namespace) -> int:
    """Emit the independent reviewer assignment for a task.

    The reviewer comes from a different provider family than the writer, so
    the writer is never the only judge of its own work.
    """
    root = _root(args)
    ctx = coordinator.load_context(root)
    task = ctx.backlog.tasks.get(args.task)
    if task is None:
        _emit({"ok": False, "reason": f"task {args.task} is not canonical"})
        return 1

    classification = classify.classify(task)
    inputs = ctx.routing_inputs()
    try:
        writer = routing.select(inputs, classification)
        reviewer = routing.select_reviewer(inputs, classification, writer)
    except routing.RoutingBlocked as blocked:
        _emit({"ok": False, "reason": blocked.reason, "rejections": blocked.rejections})
        return 1

    _emit(
        {
            "ok": True,
            "task": task.id,
            "writer_lane": writer.lane,
            "lane": reviewer.lane,
            "model": reviewer.harness_model,
            "effort": reviewer.effort,
            "capability_class": reviewer.capability_class,
        }
    )
    return 0


def cmd_verify_assignment(args: argparse.Namespace) -> int:
    """Re-derive the policy decision for a task and compare it to the dispatch.

    A worker is handed a lane and a model as workflow inputs, and workflow
    inputs are caller-controlled. Without this, a hand-dispatched run could
    pair frontend work with a lane forbidden to write it, or name an
    unqualified model, and would still be given the secrets. The worker
    therefore re-checks the hard policies itself rather than trusting what it
    was told. Exit code 1 means refuse to run.
    """
    root = _root(args)
    ctx = coordinator.load_context(root)
    task = ctx.backlog.tasks.get(args.task)
    if task is None:
        _emit({"ok": False, "reason": f"task {args.task} is not canonical"})
        return 1

    problems: list[str] = []
    candidate = coordinator.evaluate(ctx, task)
    classification = classify.classify(task)
    lane = ctx.policy["lanes"].get(args.lane)

    if lane is None:
        problems.append(f"lane {args.lane!r} is not defined in policy")
    else:
        if not routing._lane_may_write(lane, classification.category, "implement"):
            problems.append(
                f"lane {args.lane} may not implement {classification.category} work"
            )
        breach = routing.privacy_violation(ctx.policy, lane)
        if breach:
            problems.append(f"lane {args.lane} {breach}")

    if task.gated and not state.gate_passed(ctx.progress):
        problems.append("task is behind the mandatory real-use gate")
    if (
        any(p in task.phase for p in ("Phase D", "Phase E", "Phase F"))
        and not ctx.policy["autonomy"]["allow_phase_d_and_later"]
    ):
        problems.append(f"{task.phase} is not enabled for autonomous execution")

    satisfied, missing = state.dependencies_satisfied(ctx.progress, task.prerequisites)
    if not satisfied:
        problems.append(f"prerequisites not complete: {missing}")

    # The model must be one the catalogue actually qualified for this lane.
    qualified = {
        model_id
        for model_id, record in ctx.models_state.get("models", {}).items()
        if record.get("qualification") in ctx.policy["qualification"]["required_states"]
        and record.get("lane") == args.lane
        and not record.get("absent")
    }
    harness_names = {
        record.get("harness_model")
        for model_id, record in ctx.models_state.get("models", {}).items()
        if model_id in qualified
    }
    if args.model not in qualified and args.model not in harness_names:
        problems.append(
            f"model {args.model!r} is not a qualified model of lane {args.lane}"
        )

    if state.task_budget_exceeded(ctx.policy, ctx.budget, task.id):
        problems.append("per-task budget is already exhausted")

    if not state.autonomy_enabled(ctx.policy):
        problems.append("AUTONOMY_ENABLED is false")

    _emit(
        {
            "ok": not problems,
            "task": task.id,
            "title": task.title,
            "category": classification.category,
            "complexity": classification.complexity,
            "lane": args.lane,
            "model": args.model,
            "eligible": candidate.eligible,
            "problems": problems,
        }
    )
    return 0 if not problems else 1


def cmd_validate(args: argparse.Namespace) -> int:
    """Check every state file parses and holds the shape the system expects.

    Two workflows push `ops/state` to the same branch, so a rebase can leave
    conflict markers inside a large generated JSON file. Nothing reads these by
    hand, so that corruption is invisible until something fails to load. Every
    workflow runs this before it commits.
    """
    root = _root(args)
    paths = state.Paths(root)
    problems: list[str] = []

    expected = {
        paths.policy: ("lanes", "capability_classes"),
        paths.progress: ("completed_tasks",),
        paths.models: ("models",),
        paths.providers: ("lanes",),
        paths.tasks: ("leases",),
        paths.budget: (),
    }
    for path, keys in expected.items():
        if not path.exists():
            problems.append(f"{path.name}: missing")
            continue
        raw = path.read_text(encoding="utf-8")
        for marker in ("<<<<<<<", ">>>>>>>"):
            if any(line.startswith(marker) for line in raw.splitlines()):
                problems.append(f"{path.name}: contains merge conflict markers")
                break
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            problems.append(f"{path.name}: invalid JSON at line {exc.lineno}")
            continue
        for key in keys:
            if key not in data:
                problems.append(f"{path.name}: missing key {key!r}")

    _emit({"ok": not problems, "problems": problems})
    return 0 if not problems else 1


def cmd_dispatch(args: argparse.Namespace) -> int:
    root = _root(args)
    ctx = coordinator.load_context(root)

    if not state.autonomy_enabled(ctx.policy):
        return _emit(
            {
                "dispatched": False,
                "reason": "AUTONOMY_ENABLED is false; "
                "no implementation work is assigned",
            }
        )

    candidate = coordinator.next_eligible(ctx)
    if candidate is None:
        return _emit({"dispatched": False, "reason": "no eligible task"})

    built = coordinator.plan(ctx, candidate)
    if built.writer is None or built.reviewer is None:
        return _emit(
            {
                "dispatched": False,
                "reason": built.blocked_reason,
                "rejections": built.rejections,
            }
        )

    try:
        lease = leases.acquire(
            ctx.tasks,
            ctx.policy,
            task_id=candidate.task.id,
            owner=args.owner,
            branch=built.branch,
            assignment=built.writer.as_dict(),
            run_id=args.run_id,
        )
    except leases.LeaseConflict as conflict:
        return _emit({"dispatched": False, "reason": str(conflict)})
    except leases.AttemptsExhausted as exhausted:
        # Bounded retries: stop rather than reacquiring the task forever.
        leases.release(ctx.tasks, candidate.task.id, "blocked")
        state.write_json(ctx.paths.tasks, ctx.tasks)
        return _emit(
            {
                "dispatched": False,
                "reason": f"BLOCKED_AUTOMATION: {exhausted}",
            }
        )

    state.write_json(ctx.paths.tasks, ctx.tasks)
    payload = built.as_dict()
    payload["dispatched"] = True
    payload["lease"] = {
        k: lease[k] for k in ("owner", "branch", "expires_at", "attempts")
    }
    return _emit(payload)


def cmd_notify(args: argparse.Namespace) -> int:
    root = _root(args)
    policy = state.load_policy(state.Paths(root))
    # Create the feed if this repository has none. Looking it up and giving up
    # meant a fresh repository silently dropped every event.
    issue = args.issue or notify.ensure_feed(policy, repo=args.repo)
    if issue is None:
        title = policy["notifications"]["issue_title"]
        return _emit(
            {"ok": False, "reason": f"could not find or create issue {title!r}"}
        )
    ok = notify.post(
        issue,
        args.kind,
        args.headline,
        json.loads(args.details or "{}"),
        repo=args.repo,
    )
    return _emit({"ok": ok, "issue": issue})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentops")
    parser.add_argument("--root", default=".", help="repository root")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="current orchestrator state").set_defaults(
        func=cmd_status
    )
    sub.add_parser("plan", help="dry-run the next task selection").set_defaults(
        func=cmd_plan
    )
    sub.add_parser("discover", help="refresh the model catalogue").set_defaults(
        func=cmd_discover
    )

    qualify_cmd = sub.add_parser(
        "qualify", help="run the synthetic qualification suite"
    )
    qualify_cmd.add_argument("--model", action="append")
    qualify_cmd.add_argument("--lane")
    qualify_cmd.add_argument("--limit", type=int, default=3)
    qualify_cmd.add_argument(
        "--against",
        default="ROUTINE_CODING",
        help="capability class the candidates must already clear",
    )
    qualify_cmd.set_defaults(func=cmd_qualify)

    health = sub.add_parser("health", help="read or set provider health")
    health.add_argument(
        "--probe",
        action="store_true",
        help="promote lanes whose secret is present, demote those without",
    )
    health.add_argument("--lane")
    health.add_argument("--status", default="AVAILABLE")
    health.add_argument("--reason")
    health.add_argument("--reset-at")
    health.set_defaults(func=cmd_health)

    dispatch = sub.add_parser("dispatch", help="assign the next task to a worker")
    dispatch.add_argument("--owner", default="coordinator")
    dispatch.add_argument("--run-id", dest="run_id")
    dispatch.set_defaults(func=cmd_dispatch)

    verify = sub.add_parser(
        "verify-assignment",
        help="re-check a dispatched assignment against policy; exit 1 to refuse",
    )
    verify.add_argument("--task", type=int, required=True)
    verify.add_argument("--lane", required=True)
    verify.add_argument("--model", required=True)
    verify.set_defaults(func=cmd_verify_assignment)

    reviewer = sub.add_parser(
        "reviewer", help="print the independent reviewer assignment for a task"
    )
    reviewer.add_argument("--task", type=int, required=True)
    reviewer.set_defaults(func=cmd_reviewer)

    lane_q = sub.add_parser(
        "qualify-lane", help="record that a lane was proven end to end"
    )
    lane_q.add_argument("--lane", required=True)
    lane_q.add_argument("--evidence", required=True)
    lane_q.set_defaults(func=cmd_qualify_lane)

    exhausted = sub.add_parser(
        "exhausted", help="cool a subscription lane down until its window resets"
    )
    exhausted.add_argument("--lane", required=True)
    exhausted.add_argument("--reason")
    exhausted.add_argument("--window", type=int)
    exhausted.set_defaults(func=cmd_exhausted)

    sub.add_parser(
        "validate", help="check the state files parse and are well formed"
    ).set_defaults(func=cmd_validate)

    spend = sub.add_parser("spend", help="record API spend for a lane")
    spend.add_argument("--lane", required=True)
    spend.add_argument("--usd", type=float, required=True)
    spend.add_argument("--task", type=int)
    spend.set_defaults(func=cmd_spend)

    feed = sub.add_parser("notify", help="post one milestone to the activity feed")
    feed.add_argument("kind")
    feed.add_argument("headline")
    feed.add_argument("--details")
    feed.add_argument("--issue", type=int)
    feed.add_argument("--repo")
    feed.set_defaults(func=cmd_notify)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result: int = args.func(args)
        return result
    except routing.RoutingBlocked as blocked:
        print(json.dumps({"blocked": blocked.reason, "rejections": blocked.rejections}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
