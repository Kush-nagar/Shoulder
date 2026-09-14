"""The Control Center: one page that says what the system is doing.

The activity feed is a log -- good for "what happened at 03:14", useless for
"what is happening now", because answering that means reading to the bottom and
reconstructing it. This renders the current picture instead, and rewrites the
*body* of the same issue rather than adding another comment, so watching the
system costs one page load and the feed stays a feed.

Everything here is derived from the state files and from GitHub. Nothing is
narrated by a model, and nothing is written that the next run could not
reconstruct.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from . import coordinator, leases, notify, state

TITLE = "Shoulder AgentOps Control Center"
BODY_MARKER = "<!-- agentops:control-center -->"

# Lease state to the vocabulary a reader expects. The lease is the durable
# record; these names are what it means.
STAGE_NAMES = {
    "assigned": "LEASED",
    "implementing": "IMPLEMENTING",
    "verifying": "CHECKPOINTED",
    "ci": "CI_RUNNING",
    "review": "REVIEWING",
    "repairing": "REPAIRING",
    "merged": "MERGED",
    "blocked": "BLOCKED_GATE",
    "abandoned": "FAILED_INFRASTRUCTURE",
}


def _joined(values: list[str] | None) -> str:
    return ", ".join(values or []) or "—"


def _gh(args: list[str], *, repo: str | None = None) -> str | None:
    command = ["gh", *args]
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
    return result.stdout if result.returncode == 0 else None


def pull_request_checks(
    pull_request: int, *, repo: str | None = None
) -> list[dict[str, str]]:
    """Each check on a pull request and how it ended.

    Read rather than remembered: a state file saying CI passed is a claim about
    the past, and the point of this page is that a reader does not have to
    trust one.
    """
    raw = _gh(
        [
            "pr",
            "view",
            str(pull_request),
            "--json",
            "statusCheckRollup",
        ],
        repo=repo,
    )
    if not raw:
        return []
    try:
        rollup = (json.loads(raw) or {}).get("statusCheckRollup") or []
    except json.JSONDecodeError:
        return []
    checks = []
    for check in rollup:
        name = check.get("name") or check.get("context") or "check"
        result = (
            check.get("conclusion") or check.get("state") or check.get("status") or ""
        )
        checks.append({"name": str(name), "result": str(result).upper() or "PENDING"})
    return checks


def _autonomy_status(
    ctx: coordinator.Context, active: list[dict[str, Any]]
) -> tuple[str, str]:
    if not state.autonomy_enabled(ctx.policy):
        return "PAUSED", "AUTONOMY_ENABLED is false"
    if active:
        return "RUNNING", f"{len(active)} task in flight"
    blocked = [
        lease
        for lease in ctx.tasks.get("leases", {}).values()
        if lease.get("state") == "blocked"
    ]
    candidate = coordinator.next_eligible(ctx)
    if candidate is not None:
        return "IDLE", "an eligible task is waiting for the next coordinator run"
    if blocked:
        return "BLOCKED", f"{len(blocked)} task held after exhausting its attempts"
    return "BLOCKED", "no task is eligible; every remaining path is gated"


def _gates(ctx: coordinator.Context) -> list[str]:
    """Real gates standing between the system and the rest of the backlog."""
    out = []
    if not state.gate_passed(ctx.policy, ctx.progress):
        out.append(
            "**real_use_gate** — Task 23 onward needs real coach and player use of "
            "the manual product plus the human judgments that come out of it. No "
            "cloud agent can supply that; a human sets `gates.real_use_gate`."
        )
    if not ctx.policy["autonomy"]["allow_phase_d_and_later"]:
        out.append(
            "**allow_phase_d_and_later** — AGENTS.md rule 5 forbids ML work before "
            "the gate, so Phase D, E and F stay closed to autonomous execution."
        )
    return out


def render(root: Path, *, repo: str | None = None) -> str:
    ctx = coordinator.load_context(root)
    active = leases.active_leases(ctx.tasks, ctx.policy)
    status, why = _autonomy_status(ctx, active)
    done = sorted(state.completed_tasks(ctx.progress))

    lines = [
        BODY_MARKER,
        f"# {TITLE}",
        "",
        f"**AUTONOMY STATUS: {status}** — {why}",
        "",
        f"_Last heartbeat: {state.now()}_",
        "",
        "## Current task",
        "",
    ]

    if active:
        for lease in active:
            task_id = int(lease.get("task_id", 0))
            task = ctx.backlog.tasks.get(task_id)
            assignment = lease.get("assignment") or {}
            stage = STAGE_NAMES.get(str(lease.get("state")), str(lease.get("state")))
            pr = lease.get("pull_request")
            lines += [
                f"- **Task {task_id} — {task.title if task else 'unknown'}**",
                f"- Phase: {task.phase if task else 'unknown'}",
                f"- Stage: `{stage}`",
                f"- Branch: `{lease.get('branch')}`",
                f"- Pull request: {f'#{pr}' if pr else 'not opened yet'}",
                f"- Provider: `{assignment.get('lane')}`"
                f" running `{assignment.get('model') or 'account-configured'}`"
                f" at {assignment.get('effort')} effort",
                f"- Attempts: {lease.get('attempts', 0)}"
                f" · CI repairs: {lease.get('ci_repair_cycles', 0)}"
                f" · review repairs: {lease.get('review_repair_cycles', 0)}",
                f"- Owner run: `{lease.get('worker_run_id') or lease.get('owner')}`",
                f"- Last heartbeat: {lease.get('heartbeat_at')}",
            ]
            checkpoint = lease.get("checkpoint") or {}
            if checkpoint:
                lines += [
                    "",
                    "### Last durable checkpoint",
                    "",
                    f"- At: {checkpoint.get('at')} (`{checkpoint.get('state')}`)",
                    f"- Commit: `{checkpoint.get('commit') or 'none recorded'}`",
                    f"- Complete: {_joined(checkpoint.get('complete'))}",
                    f"- Remaining: {_joined(checkpoint.get('remaining'))}",
                    f"- Next action: {checkpoint.get('next_action') or '—'}",
                ]
            if pr and repo:
                checks = pull_request_checks(int(pr), repo=repo)
                lines += ["", "### Checks", ""]
                lines += (
                    [f"- `{c['name']}`: **{c['result']}**" for c in checks]
                    if checks
                    else ["- no checks reported yet"]
                )
            lines.append("")
    else:
        lines += ["- none in flight", ""]

    lines += [
        "## Agent roles",
        "",
        "| Role | Who |",
        "| --- | --- |",
        "| Coordinator | `services/agentops` on GitHub Actions (deterministic) |",
        "| Writer | Claude primary; qualified OpenRouter or Codex Cloud on fallback |",
        "| Verifier | `Quality` workflow plus `scripts/check.ps1` |",
        "| Reviewer | independent lane, different provider family from the writer |",
        "| Repairer | the writer's lane, bounded by the repair ceilings |",
        "",
        "## Providers",
        "",
        "| Lane | Health | Failures | Note |",
        "| --- | --- | --- | --- |",
    ]
    health = state.provider_health(ctx.providers)
    for lane in sorted(ctx.policy["lanes"]):
        record = ctx.providers.get("lanes", {}).get(lane, {})
        lines.append(
            f"| `{lane}` | {health.get(lane, 'UNKNOWN')} "
            f"| {record.get('failure_count', 0)} "
            f"| {notify.redact(str(record.get('reason') or ''))} |"
        )

    spend = ctx.budget.get("spend", {}).get("daily", {}).get(state.today(), {})
    blocks = sorted(int(b) for b in ctx.progress.get("completed_blocks", []))
    lines += [
        "",
        f"_Fallback lanes used today: "
        f"{', '.join(f'{k} ${v}' for k, v in sorted(spend.items())) or 'none'}_",
        "",
        "## Backlog",
        "",
        f"- Completed tasks: {done}",
        f"- Completed blocks: {blocks}",
    ]

    eligible = [c for c in coordinator.candidates(ctx) if c.eligible]
    lines.append(
        "- Next eligible: "
        + (
            ", ".join(f"Task {c.task.id} ({c.task.title})" for c in eligible[:3])
            or "none"
        )
    )

    held = [
        c
        for c in coordinator.candidates(ctx)
        if not c.eligible and "already complete" not in c.reasons
    ]
    lines += ["", "## Blocked tasks", ""]
    lines += (
        [f"- Task {c.task.id} — {'; '.join(c.reasons)}" for c in held[:10]]
        if held
        else ["- none"]
    )

    gates = _gates(ctx)
    lines += ["", "## Hard gates", ""]
    lines += [f"- {g}" for g in gates] if gates else ["- none outstanding"]

    lines += [
        "",
        "---",
        "",
        "Event history is in the comments of the activity feed issue. This body is "
        "rewritten in place on every meaningful transition; it is generated by "
        "`services/agentops/control_center.py` and hand edits are overwritten.",
    ]
    return notify.redact("\n".join(lines))


CREATE_BODY = BODY_MARKER + "\n\nInitialising the control center."


def publish(root: Path, *, repo: str | None = None) -> dict[str, Any]:
    """Rewrite the Control Center issue body in place."""
    number = notify.ensure_issue(TITLE, CREATE_BODY, repo=repo)
    if number is None:
        return {"ok": False, "reason": "could not find or create the control center"}
    body = render(root, repo=repo)
    command = ["issue", "edit", str(number), "--body-file", "-"]
    full = ["gh", *command] + (["--repo", repo] if repo else [])
    result = subprocess.run(
        full,
        input=body,
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    return {
        "ok": result.returncode == 0,
        "issue": number,
        "reason": re.sub(r"\s+", " ", result.stderr)[:200] if result.returncode else "",
    }
