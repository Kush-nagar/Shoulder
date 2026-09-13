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

from . import catalog, coordinator, leases, notify, qualify, routing, state


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
    models, reason = catalog.discover()
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
        targets = [
            model_id
            for model_id, record in models_state.get("models", {}).items()
            if record.get("qualification") == "CANDIDATE"
            and (args.lane is None or record.get("lane") == args.lane)
        ][: args.limit]

    results = []
    for model_id in targets:
        result = qualify.qualify_model(
            api_key, model_id, policy, min_pass=args.min_pass
        )
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
    """Mark a lane's health. Used by workers and the watchdog."""
    root = _root(args)
    paths = state.Paths(root)
    providers = state.read_json(paths.providers, {"lanes": {}})
    if args.lane:
        state.mark_provider(
            providers,
            args.lane,
            args.status,
            reason=args.reason or "",
            reset_at=args.reset_at,
        )
        state.write_json(paths.providers, providers)
    return _emit({"provider_health": state.provider_health(providers)})


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
        )
    except leases.LeaseConflict as conflict:
        return _emit({"dispatched": False, "reason": str(conflict)})

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
    title = policy["notifications"]["issue_title"]
    issue = args.issue or notify.find_issue(title, repo=args.repo)
    if issue is None:
        return _emit(
            {"ok": False, "reason": f"activity feed issue {title!r} not found"}
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
    qualify_cmd.add_argument("--min-pass", type=int, default=None)
    qualify_cmd.set_defaults(func=cmd_qualify)

    health = sub.add_parser("health", help="read or set provider health")
    health.add_argument("--lane")
    health.add_argument("--status", default="AVAILABLE")
    health.add_argument("--reason")
    health.add_argument("--reset-at")
    health.set_defaults(func=cmd_health)

    dispatch = sub.add_parser("dispatch", help="assign the next task to a worker")
    dispatch.add_argument("--owner", default="coordinator")
    dispatch.set_defaults(func=cmd_dispatch)

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
