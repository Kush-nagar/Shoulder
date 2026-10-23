"""Command line entry point.

Every command is safe to run by hand. Only `dispatch` starts real work, and it
refuses while autonomy is disabled.

    python -m services.agentops.cli status
    python -m services.agentops.cli plan
    python -m services.agentops.cli discover
    python -m services.agentops.cli qualify --lane openrouter
    python -m services.agentops.cli health
    python -m services.agentops.cli dispatch

The local runtime lives behind its own verbs. `run` is the only one that
starts work, and it refuses while autonomy is disabled:

    python -m services.agentops.cli doctor
    python -m services.agentops.cli run --once
    python -m services.agentops.cli serve
    python -m services.agentops.cli local-status
    python -m services.agentops.cli resume
    python -m services.agentops.cli provider openrouter
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import (
    approvals,
    catalog,
    classify,
    control_center,
    coordinator,
    dashboard,
    governance,
    leases,
    local,
    localstate,
    notify,
    project,
    qualify,
    reconcile,
    review,
    routing,
    state,
    statebranch,
    toolchain,
    watchdog,
)


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
            # From policy, which is on the protected branch. The ledger's
            # copy is historical and cannot grant a gate.
            "gates": ctx.policy.get("gates", {}),
            "state_branch": statebranch.BRANCH,
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

            # A lane that failed, or is cooling down, is not restored by a
            # probe. Presence of a credential is not evidence that the provider
            # is working, and overwriting the failure would erase the very
            # signal that makes failover happen.
            if health.get(lane_name) in (
                "COOLDOWN",
                "AUTH_FAILED",
                "DEGRADED",
                "BUDGET_EXHAUSTED",
            ):
                continue

            secret = lane.get("secret")
            if not secret:
                # A secretless lane is subscription-backed and reached through
                # an account-level integration rather than a credential this
                # repository holds -- Codex Cloud through the GitHub app. There
                # is nothing here to probe, so an existing cooldown is the only
                # thing that may keep it out of the pool.
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


VERDICT_FIELDS = (
    "qualification",
    "qualification_evidence",
    "qualification_probes",
)


def cmd_merge_verdicts(args: argparse.Namespace) -> int:
    """Re-apply qualification verdicts from a saved catalogue onto the current one.

    A verify run refreshes the whole catalogue before it qualifies anything, so
    its `models.json` differs from the branch's in every `last_seen` timestamp.
    Rebasing that against another writer's commit conflicts on a generated file,
    which is how two runs lost verdicts they had already paid for.

    This is the read-modify-write retry used elsewhere for spend and lease
    attachment: take the remote's state as the base, then re-apply only the
    fields this run actually produced. Running it twice changes nothing.
    """
    root = _root(args)
    paths = state.Paths(root)
    saved = catalog.load_state(Path(args.source))
    current = catalog.load_state(paths.models)

    applied: list[str] = []
    for model_id, record in saved.get("models", {}).items():
        if "qualification" not in record:
            continue
        target = current.setdefault("models", {}).setdefault(model_id, {})
        if all(target.get(f) == record.get(f) for f in VERDICT_FIELDS):
            continue
        for field in VERDICT_FIELDS:
            if field in record:
                target[field] = record[field]
        applied.append(model_id)

    if applied:
        catalog.save_state(paths.models, current)
    return _emit({"ok": True, "applied": sorted(applied)})


def cmd_spend(args: argparse.Namespace) -> int:
    """Record API spend against a lane and, when given, a task."""
    root = _root(args)
    paths = state.Paths(root)
    policy = state.load_policy(paths)

    # A subscription lane spends an allowance, not money. Adding it to a dollar
    # ledger would block a task on a per-task ceiling nobody actually spent,
    # and would make the OpenRouter ceilings meaningless.
    lane = policy["lanes"].get(args.lane, {})
    if lane.get("billing") != "api":
        return _emit(
            {
                "ok": True,
                "lane": args.lane,
                "recorded_usd": 0.0,
                "skipped": "subscription lanes spend an allowance, not the budget",
            }
        )

    budget = state.read_json(paths.budget, {"spend": {}})
    state.record_spend(
        budget, args.lane, args.usd, task_id=args.task, once_key=args.once_key
    )
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


def _writer_lane_from_pull_request(number: int, repo: str | None) -> str:
    """The writer lane a pull request records in its own body.

    Read from GitHub rather than from local state, because the review workflow
    runs on a checkout that has neither the branch's lease nor its worktree.
    A failure to read it is not an error here: the caller treats an unknown
    writer as a refusal, which is the safe direction.
    """
    command = ["pr", "view", str(number), "--json", "body"]
    if repo:
        command += ["--repo", repo]
    try:
        result = subprocess.run(
            ["gh", *command],
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return ""
    return project.writer_lane_of(str(payload.get("body") or ""))


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

    # Who actually wrote this branch, from the lease. Recomputing it would ask
    # who would write it *now*: if a lane was unavailable at dispatch and has
    # since recovered, the writer could be named as its own reviewer.
    lease = ctx.tasks.get("leases", {}).get(str(args.task)) or {}
    recorded = (lease.get("assignment") or {}).get("lane")
    source = "lease" if recorded else ""

    # Failing that, what the pull request itself says. The lease that records
    # the writer lives in the local runtime's ignored state, which the review
    # workflow cannot see, so in this deployment the lease is almost never
    # there and the fallback below is what actually runs.
    if not recorded and getattr(args, "pull_request", None):
        recorded = _writer_lane_from_pull_request(args.pull_request, args.repo)
        source = "pull-request" if recorded else source

    if not recorded or recorded not in ctx.policy["lanes"]:
        # Deliberately not a guess. Recomputing the writer here is what put
        # Claude forward to review a branch Claude had written: routing had
        # changed since dispatch, so the recomputed writer was Codex, the
        # Anthropic family looked independent, and the merge gate would have
        # accepted a self-review as the independent one. An unknown writer
        # means no reviewer can be shown to be independent, and saying so is
        # the only safe answer.
        _emit(
            {
                "ok": False,
                "task": task.id,
                "reason": (
                    "cannot establish which lane wrote this branch, so no "
                    "reviewer can be shown to be independent of it"
                ),
                "remedy": (
                    "pass --pull-request so the writer marker in its body can "
                    "be read, or run where the lease ledger is visible"
                ),
            }
        )
        return 1

    # A lane the caller cannot actually start is not a reviewer. The local
    # Codex lane runs `codex exec` on this workstation against a subscription
    # that exists nowhere else, so a GitHub Actions job that chose it would
    # find no step to run, report success having reviewed nothing, and leave
    # the verdict waiting forever for a review that cannot arrive.
    unusable = {
        name
        for name, lane in ctx.policy["lanes"].items()
        if str(lane.get("mechanism", "")) in set(args.exclude_mechanism or ())
    }
    try:
        writer_family = ctx.policy["lanes"][recorded]["provider"]
        reviewer = routing.select(
            inputs,
            classification,
            purpose="review",
            exclude_family=writer_family,
            exclude_lanes=frozenset(unusable),
        )
        writer_lane = recorded
    except routing.RoutingBlocked as blocked:
        _emit({"ok": False, "reason": blocked.reason, "rejections": blocked.rejections})
        return 1

    _emit(
        {
            "ok": True,
            "task": task.id,
            "writer_lane": writer_lane,
            "writer_source": source,
            "writer_from_lease": source == "lease",
            "lane": reviewer.lane,
            "model": reviewer.harness_model,
            "effort": reviewer.effort,
            "capability_class": reviewer.capability_class,
            # The merge gate needs both. `mechanism` says whether this reviewer
            # answers inside its own job or asynchronously afterwards, and the
            # login says whose answer to wait for. Without them the gate either
            # cannot wait or waits for anyone at all.
            "mechanism": reviewer.mechanism,
            "review_bot_login": ctx.policy["lanes"][reviewer.lane].get(
                "review_bot_login"
            ),
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
    # The worker exists because a lease was taken for this task, so its own
    # lease is not a conflict. Everything else about eligibility still applies.
    candidate = coordinator.evaluate(ctx, task, ignore_own_lease=True)
    classification = classify.classify(task)

    held = ctx.tasks.get("leases", {}).get(str(args.task)) or {}
    if held.get("state") not in leases.ACTIVE_STATES:
        problems.append(
            f"task {args.task} has no active lease; a worker runs only against one"
        )
    else:
        # The lease records what was actually assigned. Accepting any lane for
        # a task that merely has *a* lease would let a manual dispatch run a
        # different provider than the one the coordinator chose and recorded.
        leased = held.get("assignment") or {}
        if leased.get("lane") and leased["lane"] != args.lane:
            problems.append(f"the lease assigns lane {leased['lane']}, not {args.lane}")
        # A manual replay with the exact leased task, lane, model and branch
        # would otherwise pass. Once a worker has attached its run, the lease
        # belongs to that run, and the branch concurrency group queues a second
        # same-branch run rather than rejecting it.
        # The run id alone is stable across a re-run of the same workflow, so
        # a replay would match it. The attempt is what distinguishes them.
        attached = held.get("worker_run_id")
        attached_attempt = held.get("worker_run_attempt")
        if attached and args.run_id and str(attached) != str(args.run_id):
            problems.append(
                f"the lease is held by worker run {attached}, not {args.run_id}"
            )
        elif (
            attached_attempt
            and args.run_attempt
            and str(attached_attempt) != str(args.run_attempt)
        ):
            problems.append(
                f"the lease is held by attempt {attached_attempt} of that run, "
                f"not attempt {args.run_attempt}"
            )
        if args.branch and held.get("branch") and held["branch"] != args.branch:
            problems.append(
                f"the lease is on branch {held['branch']!r}, not {args.branch!r}"
            )
        leased_model = leased.get("harness_model")
        if (
            leased_model
            and leased.get("model_enforced", True)
            and leased_model != args.model
        ):
            problems.append(
                f"the lease assigns model {leased_model!r}, not {args.model!r}"
            )
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

    if task.gated and not state.gate_passed(ctx.policy, ctx.progress):
        problems.append("task is behind the mandatory real-use gate")
    if (
        any(p in task.phase for p in ("Phase D", "Phase E", "Phase F"))
        and not ctx.policy["autonomy"]["allow_phase_d_and_later"]
    ):
        problems.append(f"{task.phase} is not enabled for autonomous execution")

    satisfied, missing = state.dependencies_satisfied(ctx.progress, task.prerequisites)
    if not satisfied:
        problems.append(f"prerequisites not complete: {missing}")

    # Re-derive the decision rather than re-checking fragments of it. Hand
    # checks missed lane enablement, provider health, budget ceilings, the
    # capability class, cheapest-model selection, and lane qualification, so a
    # manual dispatch could send complex work to an undersized model.
    try:
        routed = routing.select(ctx.routing_inputs(), classification)
    except routing.RoutingBlocked as blocked:
        problems.append(f"routing would not choose any lane: {blocked.reason}")
    else:
        if routed.lane != args.lane:
            problems.append(f"routing chose lane {routed.lane}, not {args.lane}")
        elif args.model not in (routed.model, routed.harness_model):
            # A lane that cannot be told which model to use is exempt: the
            # recorded tier is advisory there, so the slug is not binding.
            if routed.model_enforced:
                problems.append(
                    f"routing chose model {routed.harness_model!r}, not {args.model!r}"
                )

    if state.task_budget_exceeded(ctx.policy, ctx.budget, task.id):
        problems.append("per-task budget is already exhausted")

    # Eligibility was computed and then only reported. A manual dispatch could
    # therefore re-run a task that is already complete, or start a second
    # writer on one that is already leased.
    if not candidate.eligible:
        problems.append(f"task is not eligible: {'; '.join(candidate.reasons)}")

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


def cmd_usage(args: argparse.Namespace) -> int:
    """Read a provider's own usage and remaining limit, where it exposes one.

    The local ledger only knows what this system recorded. OpenRouter reports
    the account's actual spend and remaining credit, so a lane can be cooled
    on the provider's numbers rather than on an estimate. Codex and Claude
    expose no equivalent on consumer plans, which is why exhaustion there is
    inferred from a run that could not proceed.
    """
    import urllib.error
    import urllib.request

    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        _emit({"ok": False, "reason": "OPENROUTER_API_KEY is not set"})
        return 1

    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/key",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        _emit({"ok": False, "reason": f"{type(exc).__name__}: {exc}"})
        return 1

    data = payload.get("data", payload)
    # Never echo the key's label or anything identifying; only the numbers.
    reported = {
        key: data.get(key)
        for key in (
            "limit",
            "limit_remaining",
            "usage",
            "usage_daily",
            "usage_weekly",
            "usage_monthly",
            "is_free_tier",
        )
    }

    root = _root(args)
    paths = state.Paths(root)
    policy = state.load_policy(paths)
    ceiling = float(policy["budget"]["openrouter_daily_usd"])
    daily = float(reported.get("usage_daily") or 0.0)
    exhausted = bool(
        reported.get("limit_remaining") is not None
        and float(reported["limit_remaining"]) <= 0
    )

    # Reporting an overrun and doing nothing leaves the lane eligible. Routing
    # reads budget and health, so the provider's own numbers have to land in
    # one of them or this check changes nothing.
    acted = ""
    if exhausted:
        providers = state.read_json(paths.providers, {"lanes": {}})
        state.mark_provider(
            providers,
            "openrouter",
            "BUDGET_EXHAUSTED",
            reason="the provider reports no remaining credit",
        )
        state.write_json(paths.providers, providers)
        acted = "marked BUDGET_EXHAUSTED"
    elif daily >= ceiling:
        budget = state.read_json(paths.budget, {"spend": {}})
        recorded = float(
            budget.get("spend", {})
            .get("daily", {})
            .get(state.today(), {})
            .get("openrouter", 0.0)
        )
        shortfall = daily - recorded
        if shortfall > 0:
            # Out-of-band charges and costs lost on failed runs never reached
            # the ledger. Reconcile up to the provider's figure so the ceiling
            # reflects what was really spent.
            state.record_spend(budget, "openrouter", shortfall)
            state.write_json(paths.budget, budget)
            acted = f"reconciled the ledger up by {shortfall:.6f}"

    return _emit(
        {
            "ok": True,
            "lane": "openrouter",
            "provider_reported": reported,
            "daily_ceiling_usd": ceiling,
            "over_daily_ceiling": daily >= ceiling,
            "credit_exhausted": exhausted,
            "action_taken": acted or "none needed",
        }
    )


def cmd_confirm_privacy(args: argparse.Namespace) -> int:
    """Record that a lane's account-level privacy settings are configured.

    Some providers enforce retention and training policy on the account rather
    than per request, and this repository cannot read that setting. Rather than
    assume it, the lane stays ineligible until the account owner confirms it
    here, with a note saying what was checked.
    """
    root = _root(args)
    paths = state.Paths(root)
    providers = state.read_json(paths.providers, {"lanes": {}})
    record = providers.setdefault("lanes", {}).setdefault(args.lane, {})
    record["privacy_confirmed"] = True
    record["privacy_confirmed_at"] = state.now()
    record["privacy_confirmation_note"] = args.note
    state.write_json(paths.providers, providers)
    return _emit({"ok": True, "lane": args.lane, "note": args.note})


def cmd_attach(args: argparse.Namespace) -> int:
    """Record the run or pull request actually doing a task's work."""
    root = _root(args)
    paths = state.Paths(root)
    tasks = state.read_json(paths.tasks, {"leases": {}})
    try:
        lease = leases.attach_worker(
            tasks,
            args.task,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            pull_request=args.pull_request,
        )
    except leases.LeaseConflict as conflict:
        _emit({"ok": False, "reason": str(conflict)})
        return 1
    state.write_json(paths.tasks, tasks)
    return _emit(
        {
            "ok": True,
            "task": args.task,
            "worker_run_id": lease.get("worker_run_id"),
            "worker_run_attempt": lease.get("worker_run_attempt"),
            "pull_request": lease.get("pull_request"),
        }
    )


def cmd_worker_finished(args: argparse.Namespace) -> int:
    """Free a lease whose worker is over and left no pull request behind.

    Run from the worker's finalize job, which only starts once the work job has
    reached a conclusion -- that job dependency is what proves the writer has
    stopped. Everything else is checked in `leases.abandon_finished_worker`,
    which refuses rather than guesses.

    A refusal is not an error. This runs on every failed worker, and most of
    those have a pull request to repair instead, so exit 0 either way and let
    the caller read `recovered`.
    """
    root = _root(args)
    paths = state.Paths(root)
    tasks = state.read_json(paths.tasks, {"leases": {}})

    # Fails closed: an unanswerable query means a pull request may exist, so
    # the lease is left for the normal stale path rather than freed on a guess.
    open_pr = watchdog.branch_pull_request_open(args.branch, repo=args.repo)
    if open_pr is None:
        return _emit(
            {
                "recovered": False,
                "task": args.task,
                "reason": "could not tell whether a pull request is open; "
                "leaving the lease alone",
            }
        )

    try:
        lease = leases.abandon_finished_worker(
            tasks,
            args.task,
            run_id=args.run_id,
            branch=args.branch,
            failure_class=args.failure_class,
            pull_request_open=open_pr,
        )
    except (leases.LeaseConflict, ValueError) as refused:
        return _emit({"recovered": False, "task": args.task, "reason": str(refused)})

    state.write_json(paths.tasks, tasks)
    return _emit(
        {
            "recovered": True,
            "task": args.task,
            "branch": args.branch,
            "failure_class": lease.get("failure_class"),
            "reason": lease.get("abandoned_reason"),
            "attempts": lease.get("attempts"),
            "checkpoint_kept": bool(lease.get("checkpoint")),
        }
    )


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
            owner_finished=lambda lease: watchdog.owner_finished(lease, repo=args.repo),
        )
    except leases.LeaseConflict as conflict:
        return _emit({"dispatched": False, "reason": str(conflict)})
    except leases.AttemptsExhausted as exhausted:
        # Bounded retries: stop rather than reacquiring the task forever.
        leases.release(ctx.tasks, candidate.task.id, "blocked")
        state.write_json(ctx.paths.tasks, ctx.tasks)

        # Blocking changes what the next eligible task is. That used to be
        # written into STATUS.md, which is on the protected default branch;
        # nothing in normal operation pushes there now, so the Control Center
        # reports it instead.
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


def cmd_repair(args: argparse.Namespace) -> int:
    """Hand a failing task back to its writer, within the repair ceilings.

    A failing check or a review finding is ordinary engineering, not a provider
    problem, so this deliberately does not change lane: it reuses the writer
    already recorded on the lease. Exit 1 means the ceiling is spent and the
    task is genuinely stuck, which is a thing to surface rather than retry.
    """
    root = _root(args)
    ctx = coordinator.load_context(root)
    try:
        lease = leases.begin_repair(
            ctx.tasks,
            ctx.policy,
            args.task,
            reason=args.reason,
            once_key=args.once_key,
        )
    except leases.RepairBudgetExhausted as spent:
        leases.release(ctx.tasks, args.task, "blocked")
        state.write_json(ctx.paths.tasks, ctx.tasks)
        return _emit(
            {
                "repair": False,
                "reason": f"BLOCKED_AUTOMATION: {spent}",
                "task": args.task,
            }
        )
    except (leases.LeaseConflict, ValueError) as problem:
        return _emit({"repair": False, "reason": str(problem), "task": args.task})

    state.write_json(ctx.paths.tasks, ctx.tasks)
    assignment = lease.get("assignment") or {}
    return _emit(
        {
            "repair": True,
            "task": args.task,
            "reason": args.reason,
            "branch": lease.get("branch"),
            "lane": assignment.get("lane"),
            "model": assignment.get("harness_model"),
            "effort": assignment.get("effort"),
            "pull_request": lease.get("pull_request"),
            "ci_repair_cycles": lease.get("ci_repair_cycles", 0),
            "review_repair_cycles": lease.get("review_repair_cycles", 0),
        }
    )


def cmd_review_verdict(args: argparse.Namespace) -> int:
    """Whether a pull request is clear to merge on review grounds.

    Exit 1 is the merge gate. It is a required status check rather than a step
    that merges by itself, so GitHub's own auto-merge does the merging and this
    system never needs to poll for green.
    """
    result = review.verdict(
        args.repo,
        args.pull_request,
        require_submitted_review=args.require_submitted_review,
        reviewer_login=args.reviewer_login,
    )
    _emit(result)
    return 0 if result.get("verdict") == "pass" else 1


def cmd_control_center(args: argparse.Namespace) -> int:
    root = _root(args)
    if args.render_only:
        print(control_center.render(root, repo=args.repo))
        return 0
    return _emit(control_center.publish(root, repo=args.repo))


def cmd_governance_check(args: argparse.Namespace) -> int:
    """Refuse an autonomous branch that changes what this system may do.

    Exit 1 blocks the merge, because the caller is a required context. The
    changed files come from the pull request itself; being unable to read them
    is also a refusal, since the alternative is guessing.
    """
    import subprocess

    result = subprocess.run(
        [
            "gh",
            "pr",
            "view",
            str(args.pull_request),
            "--repo",
            args.repo,
            "--json",
            "files",
            "--jq",
            ".files[].path",
        ],
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        _emit(
            {
                "ok": False,
                "reason": "could not read the changed files; refusing rather "
                "than guessing",
                "detail": result.stderr.strip()[:200],
            }
        )
        return 1

    changed = [line for line in result.stdout.splitlines() if line.strip()]
    found = governance.violations(changed)
    _emit({"ok": not found, "changed": len(changed), "guarded": found})
    if found:
        print(governance.refusal(found))
        return 1
    return 0


def cmd_status_snapshot(args: argparse.Namespace) -> int:
    """Rewrite the STATUS.md progress block from the current ledger.

    Deliberately a command someone runs, not something automation does. The
    file is on the protected default branch, so the only way it can change is
    through a reviewed pull request; the live view is the Control Center.
    """
    root = _root(args)
    ctx = coordinator.load_context(root)
    candidate = coordinator.next_eligible(ctx)
    updated = reconcile.update_status_file(
        root,
        ctx.progress,
        (
            f"Task {candidate.task.id} - {candidate.task.title}"
            if candidate
            else "none eligible"
        ),
    )
    return _emit({"ok": True, "status_file_updated": updated})


def cmd_state_pull(args: argparse.Namespace) -> int:
    """Bring the runtime ledger in this worktree up to the state branch.

    Every job that reads or writes state runs this first. Before the branch
    exists the files committed on the default branch are the seed, so a fresh
    repository and a migrating one take the same path.
    """
    try:
        return _emit(statebranch.pull(_root(args)))
    except statebranch.StateBranchError as failure:
        return _emit({"ok": False, "reason": str(failure)}) or 1


def cmd_state_push(args: argparse.Namespace) -> int:
    """Commit the runtime ledger onto the state branch.

    Exit 1 means another writer landed first and nothing was written. The
    caller re-reads, re-applies its change and tries again; every mutation
    here is written to be safe to repeat.
    """
    try:
        result = statebranch.push(_root(args), args.message, retries=args.retries)
    except statebranch.StateBranchError as failure:
        _emit({"pushed": False, "reason": str(failure)})
        return 1
    _emit(result)
    return 0 if result.get("pushed") else 1


def cmd_state_contents(args: argparse.Namespace) -> int:
    """Every path the state branch holds. Nothing outside ops/state may appear."""
    paths = statebranch.contents(_root(args))
    stray = [p for p in paths if not p.startswith(f"{statebranch.TRACKED}/")]
    _emit({"branch": statebranch.BRANCH, "paths": paths, "stray": stray})
    return 0 if not stray else 1


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


# --------------------------------------------------------------------------
# The local runtime
# --------------------------------------------------------------------------


def _local_paths(args: argparse.Namespace) -> localstate.LocalPaths:
    return localstate.ensure(localstate.LocalPaths(_root(args)))


def cmd_run(args: argparse.Namespace) -> int:
    """Run local iterations until there is nothing eligible left to do.

    Refuses while autonomy is disabled, exactly as `dispatch` does: a local
    runtime is not an exception to the switch, it is another way to obey it.
    """
    root = _root(args)
    paths = _local_paths(args)
    if args.enable:
        # Typing the command is the authorisation. It is recorded locally and
        # never touches ops/policy.json, so cloud autonomy stays exactly as it
        # was.
        local.enable_local(paths)
    localstate.write(
        paths.runtime,
        {
            "pid": os.getpid(),
            "image": Path(sys.executable).name,
            "started_at": localstate.now(),
            "state": "running",
            "root": str(root),
        },
    )
    results = []
    try:
        for _ in range(max(1, args.iterations)):
            result = local.run_once(
                root,
                paths,
                verification_kind=args.verification,
                review=not args.no_review,
            )
            results.append(result)
            if not result.get("dispatched"):
                break
            if args.once:
                break
    finally:
        localstate.write(
            paths.runtime,
            {
                "pid": os.getpid(),
                "image": Path(sys.executable).name,
                "stopped_at": localstate.now(),
                "state": "stopped",
                "root": str(root),
            },
        )
    return _emit({"iterations": len(results), "results": results})


def cmd_serve(args: argparse.Namespace) -> int:
    """Serve the read-only dashboard on the loopback interface."""
    root = _root(args)
    paths = _local_paths(args)
    config = localstate.load_config(paths)
    host = args.host or config["dashboard"]["host"]
    port = int(args.port or config["dashboard"]["port"])
    print(f"AgentOps local dashboard on http://{host}:{port}/ (Ctrl+C to stop)")
    try:
        dashboard.serve(root, paths, host=host, port=port)
    except KeyboardInterrupt:
        pass
    return 0


def cmd_project(args: argparse.Namespace) -> int:
    """Work the canonical backlog to the end, or until a person is needed.

    Exit 1 means it stopped on a blocker. The blocker's name is in the payload
    and the work it stopped on is intact: nothing here discards a branch, a
    worktree or an edit to make a stop look tidier.
    """
    result = project.run_project(
        _root(args),
        _local_paths(args),
        repo=args.repo,
        verification=args.verification,
        max_tasks=args.max_tasks,
        poll_seconds=args.poll_seconds,
        gate_timeout_seconds=args.gate_timeout,
    )
    _emit(result)
    return 0 if result["status"] in (project.COMPLETE, project.RUNNING) else 1


def cmd_resume(args: argparse.Namespace) -> int:
    """Say what the last run left behind, without destroying any of it.

    Including the project loop's own position: which task, branch, worktree and
    pull request it was on, and which provider is cooling down. Restarting
    `project` from that point continues rather than redoing, because every
    phase is re-derived from Git, GitHub and the lease ledger.
    """
    root = _root(args)
    paths = _local_paths(args)
    return _emit(
        {
            **local.recover(root, paths),
            "project": project.status(root, paths),
        }
    )


def cmd_stop(args: argparse.Namespace) -> int:
    """Ask a running local coordinator to stop.

    Only the coordinator is signalled. A worker that is mid-edit is left to
    finish or to be found by recovery, because killing it is how a worktree
    ends up half written with nothing recording why.
    """
    paths = _local_paths(args)
    # Stopping means stop scheduling locally. Cloud policy is not consulted
    # and not changed.
    local.disable_local(paths)
    runtime = localstate.read(paths.runtime, {})
    raw = str(runtime.get("pid") or "")
    pid = int(raw) if raw.isdigit() else None
    # With the image as well as the number: after the coordinator exits, its
    # pid can be reused, and an unconditional SIGTERM would then kill whatever
    # inherited it.
    image = str(runtime.get("image") or "")
    if pid is None or not localstate.process_alive(pid, image or None):
        return _emit(
            {
                "stopped": False,
                "local_enabled": False,
                "reason": "local scheduling disabled; no runtime process was running",
            }
        )
    try:
        os.kill(pid, signal.SIGTERM)
    except (OSError, ValueError) as failure:
        return _emit({"stopped": False, "reason": str(failure)})
    localstate.append_event(paths, "runtime_stopped", pid=pid)
    return _emit({"stopped": True, "pid": pid, "local_enabled": False})


def cmd_enable_local(args: argparse.Namespace) -> int:
    """Authorise local execution on this machine, and nothing else.

    `run --enable` already does this, but only as a side effect of starting
    iterations, so the project loop and the launcher had no way to ask for the
    authorisation without also asking for work. Cloud autonomy lives in
    ops/policy.json, stays off, and is not read or written here.
    """
    paths = _local_paths(args)
    return _emit(local.enable_local(paths))


def cmd_provider(args: argparse.Namespace) -> int:
    """Show or switch the provider a local worker runs against.

    Switching records the choice and nothing else. The OpenRouter key is read
    from the environment when a worker spawns and is never stored here.
    """
    paths = _local_paths(args)
    config = localstate.load_config(paths)
    if args.choice != "status":
        config["provider"] = args.choice
        localstate.save_config(paths, config)
    status = local.provider_status(config)
    # A lane parked because its allowance ran out is not a failure and not a
    # setting; it is a clock. Saying when it comes back is the whole point.
    status["cooldowns"] = local.provider_cooldowns(paths)
    if status["status"] == "AVAILABLE_LATER":
        status["how_to_enable"] = (
            f"set {local.OPENROUTER_KEY_ENV} in the shell that starts the runtime, "
            "then run: python -m services.agentops.cli provider status"
        )
    return _emit(status)


def cmd_local_status(args: argparse.Namespace) -> int:
    """What the local runtime is doing, as the dashboard would show it."""
    root = _root(args)
    paths = _local_paths(args)
    data = dashboard.snapshot(root, paths)
    runtime = localstate.read(paths.runtime, {})
    data["runtime"] = {
        **runtime,
        "alive": localstate.process_alive(runtime.get("pid")),
    }
    return _emit(data)


def cmd_doctor(args: argparse.Namespace) -> int:
    """Check the things a local run needs before it needs them."""
    root = _root(args)
    paths = _local_paths(args)
    report: dict[str, Any] = {"root": str(root)}
    try:
        report["uv"] = {
            "required": toolchain.required_version(root),
            "resolved": str(toolchain.resolve_uv(root, paths)),
            "ok": True,
        }
    except (toolchain.UvUnavailable, OSError) as failure:
        # A doctor that crashes cannot diagnose anything, so a missing
        # pyproject or an unreadable binary is a finding, not a traceback.
        report["uv"] = {"ok": False, "reason": str(failure)}
    config = localstate.load_config(paths)
    report["provider"] = local.provider_status(config)
    report["harnesses"] = local.harness_status()
    enabled, why = local.local_authorized(config)
    report["local_execution"] = {"enabled": enabled, "reason": why}
    report["cloud_autonomy"] = {
        "enabled": state.autonomy_enabled(state.load_policy(state.Paths(root))),
        "note": "governed by ops/policy.json; the local runtime never changes it",
    }
    report["worktree_root"] = str(local.worktree_root(root, config))
    report["claude_binary"] = shutil.which(local.CLAUDE_BINARY) or "not on PATH"
    report["local_state"] = str(paths.dir)
    # `ok` means "the configured run can start". Reporting success while the
    # selected provider is AVAILABLE_LATER said the opposite of what it meant.
    report["ok"] = (
        bool(report["uv"].get("ok")) and report["provider"].get("status") == "AVAILABLE"
    )
    return _emit(report)


def cmd_dry_run(args: argparse.Namespace) -> int:
    """Exercise the whole local path on work that is not a backlog task."""
    return _emit(
        local.dry_run_lifecycle(_root(args), _local_paths(args), cleanup=not args.keep)
    )


def cmd_models(args: argparse.Namespace) -> int:
    """Show model approval, and what is worth evaluating next."""
    root = _root(args)
    paths = _local_paths(args)
    store = approvals.load(paths)
    models_state = state.read_json(state.Paths(root).models, {"models": {}})
    models = catalog.models_from_state(models_state)
    return _emit(
        {
            "approval": approvals.summary(store),
            "candidates": approvals.candidates(models, store),
            "harnesses": local.harness_status(),
        }
    )


def cmd_approve(args: argparse.Namespace) -> int:
    """Move one model between approval states.

    Nothing discovers its way into real work. A model takes a Shoulder task
    because somebody said it could.
    """
    paths = _local_paths(args)
    store = approvals.load(paths)
    entry = approvals.set_state(
        paths,
        store,
        args.model,
        args.state,
        risk_class=args.risk_class,
        note=args.note or "",
    )
    return _emit({"model": args.model, **entry})


def cmd_evaluate(args: argparse.Namespace) -> int:
    """Run the same throwaway task on several models and compare what happened.

    Deliberately small. It holds the task and the harness constant and reports
    what each model did with them, which is the comparison that decides an
    approval. OpenRouter's own Ori Eval is the larger tool for this and is
    documented in docs/agentops-local-runtime.md; it needs Bun and a bash
    installer, so it is not the path this repository depends on.
    """
    root = _root(args)
    paths = _local_paths(args)
    store = approvals.load(paths)
    results = []
    models_state = state.read_json(state.Paths(root).models, {"models": {}})
    known = {model.id: model.lane for model in catalog.models_from_state(models_state)}
    for model_id in args.models:
        # From the catalogue. Inferring it from a slash sent
        # `anthropic/claude-sonnet-5` to OpenCode, because namespaced ids are
        # not an OpenRouter-only shape.
        lane = known.get(model_id) or (
            "openrouter" if "/" in model_id else "claude_subscription"
        )
        allowed, reason = approvals.may_take(
            store,
            model_id,
            lane=lane,
            capability_class="CHEAP_MECHANICAL",
            purpose="evaluation",
        )
        if not allowed:
            results.append({"model": model_id, "skipped": reason})
            continue
        results.append(
            local.evaluate_model(root, paths, model_id, lane=lane, keep=args.keep)
        )
    return _emit({"evaluation": results})


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
    dispatch.add_argument("--repo")
    dispatch.set_defaults(func=cmd_dispatch)

    verify = sub.add_parser(
        "verify-assignment",
        help="re-check a dispatched assignment against policy; exit 1 to refuse",
    )
    verify.add_argument("--task", type=int, required=True)
    verify.add_argument("--lane", required=True)
    verify.add_argument("--model", required=True)
    verify.add_argument("--branch")
    verify.add_argument("--run-id", dest="run_id")
    verify.add_argument("--run-attempt", dest="run_attempt")
    verify.set_defaults(func=cmd_verify_assignment)

    reviewer = sub.add_parser(
        "reviewer", help="print the independent reviewer assignment for a task"
    )
    reviewer.add_argument("--task", type=int, required=True)
    reviewer.add_argument(
        "--pull-request",
        type=int,
        help=(
            "read the writer lane from this pull request's body when no lease "
            "records it; without it an unknown writer is a refusal"
        ),
    )
    reviewer.add_argument("--repo", help="owner/name, for --pull-request")
    reviewer.add_argument(
        "--exclude-mechanism",
        action="append",
        default=[],
        help=(
            "skip lanes reached this way, for a caller that cannot start them; "
            "GitHub Actions passes local-cli"
        ),
    )
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
        "usage", help="read OpenRouter's own reported usage and remaining limit"
    ).set_defaults(func=cmd_usage)

    privacy = sub.add_parser(
        "confirm-privacy", help="record that a lane's account privacy is configured"
    )
    privacy.add_argument("--lane", required=True)
    privacy.add_argument("--note", required=True)
    privacy.set_defaults(func=cmd_confirm_privacy)

    attach = sub.add_parser(
        "attach", help="record the run or pull request doing a task's work"
    )
    attach.add_argument("--task", type=int, required=True)
    attach.add_argument("--run-id", dest="run_id")
    attach.add_argument("--run-attempt", dest="run_attempt")
    attach.add_argument("--pull-request", dest="pull_request", type=int)
    attach.set_defaults(func=cmd_attach)

    finished = sub.add_parser(
        "worker-finished",
        help="free a lease whose worker ended without opening a pull request",
    )
    finished.add_argument("--task", type=int, required=True)
    finished.add_argument("--branch", required=True)
    finished.add_argument("--run-id", dest="run_id", required=True)
    finished.add_argument(
        "--failure-class",
        dest="failure_class",
        required=True,
        choices=sorted(leases.FAILURE_CLASSES),
    )
    finished.add_argument("--repo")
    finished.set_defaults(func=cmd_worker_finished)

    sub.add_parser(
        "validate", help="check the state files parse and are well formed"
    ).set_defaults(func=cmd_validate)

    merge_verdicts = sub.add_parser(
        "merge-verdicts",
        help="re-apply qualification verdicts from a saved catalogue",
    )
    merge_verdicts.add_argument("--from", dest="source", required=True)
    merge_verdicts.set_defaults(func=cmd_merge_verdicts)

    spend = sub.add_parser("spend", help="record API spend for a lane")
    spend.add_argument("--lane", required=True)
    spend.add_argument("--usd", type=float, required=True)
    spend.add_argument("--task", type=int)
    spend.add_argument(
        "--once-key",
        dest="once_key",
        help="apply this charge at most once, so a retry cannot double count",
    )
    spend.set_defaults(func=cmd_spend)

    repair = sub.add_parser(
        "repair", help="hand a failing task back to its writer, within the ceilings"
    )
    repair.add_argument("--task", type=int, required=True)
    repair.add_argument("--reason", required=True, choices=("ci", "review"))
    repair.add_argument(
        "--once-key",
        dest="once_key",
        help="apply this repair at most once, so a retried state write "
        "cannot spend two cycles for one failure",
    )
    repair.set_defaults(func=cmd_repair)

    verdict = sub.add_parser(
        "review-verdict",
        help="decide a pull request's review verdict; exit 1 blocks the merge",
    )
    verdict.add_argument("--repo", required=True)
    verdict.add_argument("--pull-request", dest="pull_request", type=int, required=True)
    verdict.add_argument(
        "--require-submitted-review",
        dest="require_submitted_review",
        action="store_true",
        help="the reviewer answers asynchronously; wait for a review of this head",
    )
    verdict.add_argument(
        "--reviewer-login",
        dest="reviewer_login",
        help="whose review satisfies the wait; anyone else's does not",
    )
    verdict.set_defaults(func=cmd_review_verdict)

    centre = sub.add_parser(
        "control-center", help="rewrite the Control Center issue body"
    )
    centre.add_argument("--repo")
    centre.add_argument(
        "--render-only",
        dest="render_only",
        action="store_true",
        help="print the page instead of publishing it",
    )
    centre.set_defaults(func=cmd_control_center)

    guard = sub.add_parser(
        "governance-check",
        help="refuse an autonomous branch that changes policy, workflows or gates",
    )
    guard.add_argument("--repo", required=True)
    guard.add_argument("--pull-request", dest="pull_request", type=int, required=True)
    guard.set_defaults(func=cmd_governance_check)

    sub.add_parser(
        "status-snapshot",
        help="rewrite the STATUS.md progress block; commit it through a pull request",
    ).set_defaults(func=cmd_status_snapshot)

    state_pull = sub.add_parser(
        "state-pull", help="read the runtime ledger from the state branch"
    )
    state_pull.set_defaults(func=cmd_state_pull)

    state_push = sub.add_parser(
        "state-push", help="write the runtime ledger to the state branch"
    )
    state_push.add_argument("--message", required=True)
    state_push.add_argument(
        "--retries",
        type=int,
        default=0,
        help="re-apply this run's files and try again on a lost race. Only for "
        "a caller that cannot re-run its own mutation; re-applying overwrites "
        "the winner when both writers touched the same file.",
    )
    state_push.set_defaults(func=cmd_state_push)

    sub.add_parser(
        "state-contents",
        help="list what the state branch holds; exit 1 on a stray path",
    ).set_defaults(func=cmd_state_contents)

    feed = sub.add_parser("notify", help="post one milestone to the activity feed")
    feed.add_argument("kind")
    feed.add_argument("headline")
    feed.add_argument("--details")
    feed.add_argument("--issue", type=int)
    feed.add_argument("--repo")
    feed.set_defaults(func=cmd_notify)

    run = sub.add_parser(
        "run", help="run the local runtime: decide, lease, implement, verify"
    )
    run.add_argument(
        "--once", action="store_true", help="stop after one dispatched task"
    )
    run.add_argument(
        "--iterations",
        type=int,
        default=1,
        help="how many tasks to attempt before stopping",
    )
    run.add_argument(
        "--enable",
        action="store_true",
        help="authorise local execution on this machine (local state only)",
    )
    run.add_argument(
        "--no-review",
        action="store_true",
        help="skip the local review stage (diagnostics only)",
    )
    run.add_argument(
        "--verification",
        choices=["fast", "gated"],
        default="fast",
        help="fast is the Python gate; gated adds the shared-port suite",
    )
    run.set_defaults(func=cmd_run)

    serve = sub.add_parser("serve", help="serve the read-only local dashboard")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.set_defaults(func=cmd_serve)

    project_cmd = sub.add_parser(
        "project", help="work the canonical backlog to the end"
    )
    project_cmd.add_argument("--repo", help="owner/name; discovered from gh if omitted")
    project_cmd.add_argument(
        "--verification", choices=["fast", "gated"], default="gated"
    )
    project_cmd.add_argument(
        "--max-tasks", type=int, help="stop after this many merges"
    )
    project_cmd.add_argument(
        "--poll-seconds", type=int, default=project.DEFAULT_POLL_SECONDS
    )
    project_cmd.add_argument(
        "--gate-timeout", type=int, default=project.DEFAULT_GATE_TIMEOUT_SECONDS
    )
    project_cmd.set_defaults(func=cmd_project)

    sub.add_parser(
        "resume", help="classify what the last local run left behind"
    ).set_defaults(func=cmd_resume)

    sub.add_parser("stop", help="stop a running local coordinator").set_defaults(
        func=cmd_stop
    )

    sub.add_parser(
        "enable-local", help="authorise local execution on this machine"
    ).set_defaults(func=cmd_enable_local)

    sub.add_parser(
        "local-status", help="what the local runtime is doing, as JSON"
    ).set_defaults(func=cmd_local_status)

    sub.add_parser(
        "doctor", help="check uv, provider and harness before a run needs them"
    ).set_defaults(func=cmd_doctor)

    dry = sub.add_parser(
        "dry-run", help="exercise the local path on a throwaway branch"
    )
    dry.add_argument(
        "--keep", action="store_true", help="leave the worktree and branch in place"
    )
    dry.set_defaults(func=cmd_dry_run)

    provider = sub.add_parser(
        "provider", help="show or switch the local worker provider"
    )
    provider.add_argument(
        "choice",
        nargs="?",
        default="status",
        choices=["status", *local.PROVIDERS],
    )
    provider.set_defaults(func=cmd_provider)

    models_cmd = sub.add_parser(
        "models", help="model approval state and evaluation candidates"
    )
    models_cmd.set_defaults(func=cmd_models)

    approve = sub.add_parser("approve-model", help="set a model's approval state")
    approve.add_argument("model")
    approve.add_argument("state", choices=list(approvals.STATES))
    approve.add_argument("--risk-class", choices=["standard", "high"])
    approve.add_argument("--note")
    approve.set_defaults(func=cmd_approve)

    evaluate = sub.add_parser(
        "evaluate", help="run one throwaway task on several models and compare"
    )
    evaluate.add_argument("models", nargs="+")
    evaluate.add_argument("--keep", action="store_true")
    evaluate.set_defaults(func=cmd_evaluate)

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
