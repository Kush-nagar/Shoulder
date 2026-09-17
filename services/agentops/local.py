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
import sys
import time
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from services.agentops import (
    brief as brief_mod,
)
from services.agentops import (
    coordinator,
    governance,
    leases,
    localstate,
    state,
    toolchain,
)

Runner = Callable[..., subprocess.CompletedProcess[str]]

CLAUDE_BINARY = os.environ.get("SHOULDER_CLAUDE_BINARY", "claude")

# OpenRouter speaks the Anthropic protocol at this address, which is why the
# same harness can drive either provider. These are the variable names the
# cloud worker already uses; keeping them identical means one thing is proven
# in both places rather than two things proven separately.
OPENROUTER_BASE_URL = "https://openrouter.ai/api"
OPENROUTER_KEY_ENV = "OPENROUTER_API_KEY"

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
    which is a state the operator can see and fix rather than a crash.
    """
    provider = str(config.get("provider") or "claude")
    if provider not in PROVIDERS:
        return {
            "provider": provider,
            "status": "UNKNOWN",
            "reason": f"unknown provider; expected one of {', '.join(PROVIDERS)}",
        }
    if provider == "claude":
        return {
            "provider": "claude",
            "status": "AVAILABLE",
            "reason": "native Claude Code subscription session",
        }
    if os.environ.get(OPENROUTER_KEY_ENV, "").strip():
        return {
            "provider": "openrouter",
            "status": "AVAILABLE",
            "reason": f"{OPENROUTER_KEY_ENV} is present in the environment",
        }
    return {
        "provider": "openrouter",
        "status": "AVAILABLE_LATER",
        "reason": (
            f"{OPENROUTER_KEY_ENV} is not set in this environment. "
            "Set it in the shell that starts the runtime; it is never stored."
        ),
    }


def child_env(
    config: Mapping[str, Any], base: Mapping[str, str] | None = None
) -> dict[str, str]:
    """The environment a worker process runs with.

    The key is read here, at spawn time, straight from the parent environment.
    It is never written to configuration, state, an event, or a log, so there
    is no copy of it for anything downstream to leak.
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
    env["ANTHROPIC_BASE_URL"] = OPENROUTER_BASE_URL
    env["ANTHROPIC_AUTH_TOKEN"] = key
    env["ANTHROPIC_API_KEY"] = ""
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
    model: str, role: str, worktree: Path, config: Mapping[str, Any]
) -> list[str]:
    """The headless command line, verified against the installed CLI.

    `stream-json` refuses to run without `--verbose`, which is why it is here.
    `--permission-prompts none` denies anything that would have asked a human
    instead of waiting for one, which is what makes an unattended run safe
    without reaching for `--dangerously-skip-permissions`.

    There is deliberately no `--add-dir`. It takes a variadic list, so it ate
    the prompt that follows it and the worker started with no instructions at
    all -- it exited having done nothing, which read as a failed model rather
    than a malformed command line. The worktree is the working directory, so
    naming it again bought nothing to begin with.
    """
    budget = role_budget(config, role)
    return [
        CLAUDE_BINARY,
        "-p",
        "--model",
        model,
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-mode",
        "acceptEdits",
        "--permission-prompts",
        "none",
        "--max-turns",
        str(budget["max_turns"]),
    ]


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


def _assistant_text(event: dict[str, Any]) -> str:
    message = event.get("message") or {}
    parts = message.get("content") or []
    for part in parts:
        if isinstance(part, dict) and part.get("type") == "text":
            text = str(part.get("text") or "").strip()
            if text:
                return text[:400]
        if isinstance(part, dict) and part.get("type") == "tool_use":
            return f"tool: {part.get('name')}"
    return ""


def run_worker(
    root: Path,
    paths: localstate.LocalPaths,
    *,
    prompt: str,
    model: str,
    role: str,
    worktree: Path,
    config: Mapping[str, Any],
    run_id: str | None = None,
    popen: Callable[..., Any] | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
    on_spawn: Callable[[int], None] | None = None,
) -> dict[str, Any]:
    """Run one headless worker to completion, a timeout, or a failure.

    The wall clock is the real bound. `--max-turns` is accepted by the installed
    CLI but is not in its documented interface, so it is passed as a hint and
    never relied on as the only thing standing between a loop and the whole
    afternoon.
    """
    localstate.ensure(paths)
    run_id = run_id or uuid.uuid4().hex[:12]
    run_dir = paths.run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "brief.md").write_text(prompt, encoding="utf-8")

    argv = executor_argv(model, role, worktree, config)
    budget = role_budget(config, role)
    started = time.monotonic()

    localstate.append_event(
        paths,
        "worker_started",
        run_id=run_id,
        role=role,
        model=model,
        worktree=str(worktree),
        provider=str(config.get("provider") or "claude"),
    )

    spawn = popen or subprocess.Popen
    process = spawn(
        [*argv, prompt],
        cwd=str(worktree),
        env=child_env(config),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    # The pid has to be recorded while the process exists. Recovery asks
    # whether it is still alive, and a record with no pid reads as gone --
    # so a running worker would be classified as interrupted and its lease
    # handed to a second writer on the same branch.
    if on_spawn is not None and getattr(process, "pid", None):
        on_spawn(int(process.pid))

    result_event: dict[str, Any] = {}
    last_action = ""
    turns = 0
    timed_out = False
    stream_path = run_dir / "stdout.jsonl"

    with stream_path.open("a", encoding="utf-8", newline="\n") as stream:
        for line in process.stdout or []:
            line = line.strip()
            if not line:
                continue
            stream.write(localstate.redact(line) + "\n")
            stream.flush()
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if on_event is not None:
                on_event(event)
            if event.get("type") == "assistant":
                turns += 1
                text = _assistant_text(event)
                if text:
                    last_action = text
            elif event.get("type") == "result":
                result_event = event
            # `>=` so a zero budget stops immediately: the Windows clock
            # has ~16ms resolution, and a strict `>` reads 0.0 as "not yet".
            if time.monotonic() - started >= budget["timeout_seconds"]:
                timed_out = True
                process.kill()
                break

    stderr = ""
    try:
        _, stderr = process.communicate(timeout=60)
    except Exception:  # noqa: BLE001 - a hung child must not hang the runtime
        process.kill()
    if stderr:
        (run_dir / "stderr.log").write_text(localstate.redact(stderr), encoding="utf-8")

    returncode = process.returncode if process.returncode is not None else -1
    subtype = str(result_event.get("subtype") or "")
    ok = (not timed_out) and returncode == 0 and subtype in ("", "success")
    outcome = "timeout" if timed_out else ("completed" if ok else "failed")

    run = {
        "ok": ok,
        "outcome": outcome,
        "run_id": run_id,
        "role": role,
        "model": model,
        "returncode": returncode,
        "turns": turns,
        "elapsed_seconds": round(time.monotonic() - started, 1),
        "pid": getattr(process, "pid", None),
        "stop_reason": result_event.get("stop_reason") or result_event.get("subtype"),
        "session_id": result_event.get("session_id"),
        "usage": result_event.get("usage") or {},
        "cost_usd": float(result_event.get("total_cost_usd") or 0.0),
        "last_action": last_action,
        "stream": str(stream_path),
    }
    localstate.write(run_dir / "result.json", run)
    localstate.append_event(
        paths,
        "worker_finished",
        **{k: run[k] for k in ("run_id", "role", "outcome", "turns", "cost_usd")},
    )
    return run


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


def worker_image() -> str:
    return "claude.exe" if sys.platform == "win32" else "claude"


def resolve_uv(root: Path, paths: localstate.LocalPaths) -> Path:
    return toolchain.resolve_uv(root, paths)


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
    if outcome == "completed":
        lease["state"] = "review"
        lease["heartbeat_at"] = localstate.now()
        save_leases(paths, tasks)
        return {"lease_state": "review", "escalated": False}

    if outcome == "governance_refused":
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


def run_once(
    root: Path,
    paths: localstate.LocalPaths,
    *,
    owner: str | None = None,
    popen: Callable[..., Any] | None = None,
    runner: Runner | None = None,
    verification_kind: str = "fast",
) -> dict[str, Any]:
    """One full local iteration: decide, lease, run, judge, record.

    Every decision in here belongs to a module that already existed. What is
    new is only the part between them.
    """
    localstate.ensure(paths)
    ctx = coordinator.load_context(root)
    ctx.tasks = load_leases(root, paths)
    owner = owner or f"local-{os.getpid()}"

    if not state.autonomy_enabled(ctx.policy):
        return {
            "dispatched": False,
            "reason": "AUTONOMY_ENABLED is false; no implementation work is assigned",
        }

    candidate = coordinator.next_eligible(ctx)
    if candidate is None:
        return {"dispatched": False, "reason": "no eligible task"}

    built = coordinator.plan(ctx, candidate)
    # `blocked_reason` is set with a writer still present when the plan failed
    # for another reason -- no independent reviewer, for instance. Starting
    # anyway would run work the coordinator had already refused.
    if built.writer is None or built.blocked_reason:
        return {
            "dispatched": False,
            "reason": built.blocked_reason or "no writer could be routed",
            "rejections": built.rejections,
        }

    run_id = uuid.uuid4().hex[:12]
    try:
        leases.acquire(
            ctx.tasks,
            ctx.policy,
            task_id=candidate.task.id,
            owner=owner,
            branch=built.branch,
            assignment=built.writer.as_dict(),
            run_id=run_id,
            owner_finished=lambda held: (
                not localstate.process_alive(held.get("pid"), worker_image())
            ),
        )
    except leases.LeaseConflict as conflict:
        return {"dispatched": False, "reason": str(conflict)}
    except leases.AttemptsExhausted as exhausted:
        leases.release(ctx.tasks, candidate.task.id, "blocked")
        save_leases(paths, ctx.tasks)
        return {"dispatched": False, "reason": f"BLOCKED_AUTOMATION: {exhausted}"}
    save_leases(paths, ctx.tasks)

    config = localstate.load_config(paths)
    worktree = worktree_path(root, config, built.branch)
    create_worktree(root, built.branch, worktree, runner=runner)
    localstate.save_worker(
        paths,
        str(candidate.task.id),
        {
            "task_id": candidate.task.id,
            "task_title": candidate.task.title,
            "role": "implement",
            "branch": built.branch,
            "worktree": str(worktree),
            "lane": built.writer.lane,
            "model": built.writer.harness_model,
            "provider": config.get("provider"),
            "phase": "implementing",
            "run_id": run_id,
            "started_at": localstate.now(),
        },
    )

    run = run_worker(
        root,
        paths,
        prompt=build_prompt(root, candidate.task.id, "implement"),
        model=built.writer.harness_model,
        role="implement",
        worktree=worktree,
        config=config,
        run_id=run_id,
        popen=popen,
        on_spawn=lambda pid: localstate.save_worker(
            paths, str(candidate.task.id), {"pid": pid, "image": worker_image()}
        ),
    )

    changed = changed_paths(root, worktree, runner=runner)
    violations = governance.violations(changed)
    verification: dict[str, Any] | None = None
    if run["ok"] and not violations:
        verification = verify(
            root, paths, worktree, kind=verification_kind, owner=owner, runner=runner
        )

    outcome = classify_outcome(run, verification, violations)
    finished = _finish(
        paths, ctx.tasks, ctx.policy, candidate.task.id, outcome, once_key=run_id
    )
    localstate.save_worker(
        paths,
        str(candidate.task.id),
        {
            "phase": outcome,
            "usage": run.get("usage"),
            "cost_usd": run.get("cost_usd"),
            "last_action": run.get("last_action"),
            "verification": None if verification is None else verification["ok"],
            "changed_files": changed,
            "violations": violations,
            "finished_at": localstate.now(),
        },
    )
    localstate.append_event(
        paths,
        "task_outcome",
        task_id=candidate.task.id,
        outcome=outcome,
        lease_state=finished.get("lease_state"),
    )
    return {
        "dispatched": True,
        "task_id": candidate.task.id,
        "branch": built.branch,
        "worktree": str(worktree),
        "assignment": built.writer.as_dict(),
        "run": run,
        "violations": violations,
        "verification": verification,
        "outcome": outcome,
        **finished,
    }


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
        role="summarize",
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
