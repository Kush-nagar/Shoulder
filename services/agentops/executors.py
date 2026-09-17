"""The harnesses a local worker can actually run in.

Routing already decides the model. What it cannot decide is how that model is
driven, and the two are not the same choice: an Anthropic model runs in Claude
Code against the subscription, while DeepSeek, GLM, Kimi or Qwen need a
model-neutral coding harness. Pushing those through Claude Code's Anthropic
compatibility endpoint works in the narrow sense that bytes move, and fails in
the sense that matters -- the harness is tuned for one family's tool protocol,
and the others end up judged on someone else's prompt scaffolding.

So the harness is a small interface with two implementations, and the lane the
router already chose says which one runs. Nothing here decides which model is
worth using; it decides how to start it, how to read what came back, and
whether it can run at all on this machine.

Facts about the two command lines, established from the installed CLI and from
current published documentation rather than assumed:

* Claude Code 2.1.268: `stream-json` under `--print` requires `--verbose`;
  `--add-dir` is variadic and swallows a following prompt; `--max-turns` is
  accepted but undocumented, so the wall clock is the real bound.
* OpenCode: `opencode run <prompt> --model <provider/model> --format json
  --dir <path>` is the non-interactive form. `--auto` approves what is not
  explicitly denied, and `OPENCODE_CONFIG` points at a config file, so
  permissions and the OpenRouter key can be supplied without writing anything
  into the worktree and without putting the key in argv.
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
from typing import Any, Protocol

from services.agentops import localstate

OPENROUTER_BASE_URL = "https://openrouter.ai/api"
OPENROUTER_KEY_ENV = "OPENROUTER_API_KEY"

CLAUDE_BINARY = os.environ.get("SHOULDER_CLAUDE_BINARY", "claude")
OPENCODE_BINARY = os.environ.get("SHOULDER_OPENCODE_BINARY", "opencode")

# How OpenCode names a model routed through OpenRouter: its provider id, then
# the OpenRouter model id, which is itself `vendor/model`.
OPENCODE_PROVIDER = "openrouter"

# Read-only roles run in a mode that cannot edit. A reviewer that can edit
# stops being a reviewer the first time it decides a finding is easier to fix
# than to write down.
READ_ONLY_ROLES = ("review", "scout", "summarize")


def _text_of(event: Mapping[str, Any]) -> str:
    """The human-readable part of one harness event, whatever shape it is in.

    Neither harness guarantees this structure across versions, and OpenCode's
    published documentation does not specify its event schema at all, so this
    looks in the places both have used and gives up quietly rather than
    failing a run over a log line.
    """
    message = event.get("message")
    parts: Any = None
    if isinstance(message, Mapping):
        parts = message.get("content")
    if parts is None:
        parts = event.get("content") or event.get("parts")
    if isinstance(parts, str):
        return parts.strip()[:400]
    if isinstance(parts, list):
        for part in parts:
            if not isinstance(part, Mapping):
                continue
            if part.get("type") in ("text", "reasoning") and part.get("text"):
                return str(part["text"]).strip()[:400]
            if part.get("type") in ("tool_use", "tool", "tool-call"):
                name = part.get("name") or part.get("tool") or "tool"
                return f"tool: {name}"
    for key in ("text", "summary", "title"):
        if isinstance(event.get(key), str) and event[key].strip():
            return str(event[key]).strip()[:400]
    return ""


def _usage_of(event: Mapping[str, Any]) -> dict[str, Any]:
    usage = event.get("usage") or event.get("tokens")
    return dict(usage) if isinstance(usage, Mapping) else {}


def _cost_of(event: Mapping[str, Any]) -> float:
    for key in ("total_cost_usd", "cost_usd", "cost"):
        value = event.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return 0.0


class Executor(Protocol):
    """One way to run a coding worker."""

    name: str
    provider: str

    def available(self) -> tuple[bool, str]:
        """Whether this harness can run here, and why not when it cannot."""

    def argv(
        self, model: str, role: str, worktree: Path, budget: Mapping[str, int]
    ) -> list[str]:
        """The command line, without the prompt."""

    def env(self, base: Mapping[str, str], run_dir: Path) -> dict[str, str]:
        """The child environment. Secrets are read here and nowhere else."""

    def command(
        self,
        model: str,
        role: str,
        worktree: Path,
        budget: Mapping[str, int],
        prompt: str,
    ) -> list[str]:
        """The full command line including the prompt."""


class ClaudeCliExecutor:
    """Claude Code against the Claude subscription, on this machine.

    The already-working path. It does not go through OpenRouter and does not
    read an OpenRouter key.
    """

    name = "claude-cli"
    provider = "anthropic"

    def __init__(self, binary: str | None = None) -> None:
        self.binary = binary or CLAUDE_BINARY

    def available(self) -> tuple[bool, str]:
        found = shutil.which(self.binary)
        if not found:
            return False, f"{self.binary} is not on PATH"
        return True, f"{found}"

    def argv(
        self, model: str, role: str, worktree: Path, budget: Mapping[str, int]
    ) -> list[str]:
        # A reviewer runs in plan mode, which cannot write. `acceptEdits` is
        # for the roles whose job is to change files.
        mode = "plan" if role in READ_ONLY_ROLES else "acceptEdits"
        return [
            self.binary,
            "-p",
            "--model",
            model,
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            mode,
            "--permission-prompts",
            "none",
            "--max-turns",
            str(int(budget.get("max_turns", 20))),
        ]

    def env(self, base: Mapping[str, str], run_dir: Path) -> dict[str, str]:
        return dict(base)

    def command(
        self,
        model: str,
        role: str,
        worktree: Path,
        budget: Mapping[str, int],
        prompt: str,
    ) -> list[str]:
        # The prompt goes last and no variadic flag precedes it. `--add-dir`
        # used to: it ate the prompt, and the worker started with nothing to do.
        return [*self.argv(model, role, worktree, budget), prompt]


class OpenCodeExecutor:
    """A model-neutral coding harness, for OpenRouter models that are not Anthropic's.

    OpenCode is driven non-interactively with `opencode run`. The OpenRouter
    key never appears in argv: it is substituted by OpenCode itself from the
    environment, through a config file written per run outside the worktree, so
    the worktree diff stays exactly what the worker changed.
    """

    name = "opencode"
    provider = "openrouter"

    def __init__(self, binary: str | None = None) -> None:
        self.binary = binary or OPENCODE_BINARY

    def available(self) -> tuple[bool, str]:
        found = shutil.which(self.binary)
        if not found:
            return False, (
                f"{self.binary} is not installed. One-time install: "
                "npm install -g opencode-ai"
            )
        if not os.environ.get(OPENROUTER_KEY_ENV, "").strip():
            return False, (
                f"{OPENROUTER_KEY_ENV} is not set in this environment; "
                "OpenRouter models cannot run until it is"
            )
        return True, f"{found}"

    def model_slug(self, model: str) -> str:
        """`openrouter/vendor/model`, which is how OpenCode names it."""
        if model.startswith(f"{OPENCODE_PROVIDER}/"):
            return model
        return f"{OPENCODE_PROVIDER}/{model}"

    def config(self, role: str) -> dict[str, Any]:
        """The per-run OpenCode configuration.

        `{env:...}` is OpenCode's own substitution, so the key is read by the
        harness from the environment rather than written anywhere by us. The
        permissions are the point of writing a config at all: a worker may
        change files and run commands in its own worktree, and may not reach
        the network or outside that directory.
        """
        writable = role not in READ_ONLY_ROLES
        return {
            "$schema": "https://opencode.ai/config.json",
            "provider": {
                OPENCODE_PROVIDER: {
                    "options": {"apiKey": "{env:" + OPENROUTER_KEY_ENV + "}"}
                }
            },
            "permission": {
                "edit": "allow" if writable else "deny",
                "bash": "allow" if writable else "deny",
                "read": "allow",
                "glob": "allow",
                "grep": "allow",
                "webfetch": "deny",
                "websearch": "deny",
                "external_directory": "deny",
            },
        }

    def write_config(self, run_dir: Path, role: str) -> Path:
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / "opencode.json"
        path.write_text(
            json.dumps(self.config(role), indent=2) + "\n", encoding="utf-8"
        )
        return path

    def argv(
        self, model: str, role: str, worktree: Path, budget: Mapping[str, int]
    ) -> list[str]:
        return [
            self.binary,
            "run",
            "--model",
            self.model_slug(model),
            "--format",
            "json",
            "--dir",
            str(worktree),
            "--auto",
        ]

    def env(self, base: Mapping[str, str], run_dir: Path) -> dict[str, str]:
        """The child environment, including where its config lives.

        The key is passed through from the parent environment because OpenCode
        resolves `{env:OPENROUTER_API_KEY}` itself. It is never written to the
        config file, to argv, or to any record this runtime keeps.
        """
        env = dict(base)
        key = os.environ.get(OPENROUTER_KEY_ENV, "").strip()
        if not key:
            raise RuntimeError(
                f"{OPENROUTER_KEY_ENV} is not set; OpenRouter models cannot run"
            )
        env[OPENROUTER_KEY_ENV] = key
        env["OPENCODE_CONFIG"] = str(run_dir / "opencode.json")
        return env

    def command(
        self,
        model: str,
        role: str,
        worktree: Path,
        budget: Mapping[str, int],
        prompt: str,
    ) -> list[str]:
        return [*self.argv(model, role, worktree, budget), prompt]


def for_lane(lane: str, harness: str = "") -> Executor:
    """The harness a lane runs in.

    The lane is the decision the router already made, and the family ban in
    policy keeps Anthropic models in the subscription lane, so a lane is enough
    to decide the harness without re-deciding anything.
    """
    if lane == "openrouter":
        return OpenCodeExecutor()
    return ClaudeCliExecutor()


def availability() -> dict[str, dict[str, Any]]:
    """What can run here right now, for `doctor` and the dashboard."""
    report: dict[str, dict[str, Any]] = {}
    for executor in (ClaudeCliExecutor(), OpenCodeExecutor()):
        ok, reason = executor.available()
        report[executor.name] = {
            "available": ok,
            "reason": reason,
            "provider": executor.provider,
            "status": "AVAILABLE" if ok else "AVAILABLE_LATER",
        }
    return report


def parse_events(lines: list[str]) -> list[dict[str, Any]]:
    """Events from a harness's structured output.

    Claude Code emits one JSON object per line. OpenCode's schema is not
    published, so this also accepts a single JSON document, and an array of
    them, rather than deciding a run failed because its log was shaped
    differently than expected.
    """
    events: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            events.append(parsed)
        elif isinstance(parsed, list):
            events.extend(item for item in parsed if isinstance(item, dict))
    if events:
        return events
    whole = "\n".join(lines).strip()
    if not whole:
        return []
    try:
        parsed = json.loads(whole)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, dict):
        return [parsed]
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    return []


def run(
    executor: Executor,
    paths: localstate.LocalPaths,
    *,
    prompt: str,
    model: str,
    role: str,
    worktree: Path,
    budget: Mapping[str, int],
    run_id: str | None = None,
    popen: Callable[..., Any] | None = None,
    on_spawn: Callable[[int], None] | None = None,
) -> dict[str, Any]:
    """Run one worker to completion, a timeout, or a failure.

    The wall clock is the bound that is relied on. Claude Code's turn limit is
    undocumented and OpenCode's bounded-execution flags are not specified in
    its published documentation, so neither is trusted to stop a loop.
    """
    localstate.ensure(paths)
    run_id = run_id or uuid.uuid4().hex[:12]
    run_dir = paths.run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "brief.md").write_text(prompt, encoding="utf-8")

    if isinstance(executor, OpenCodeExecutor):
        executor.write_config(run_dir, role)

    # A caller that supplies its own launcher has supplied the harness, so
    # there is nothing to probe for. Probing anyway made every injected run
    # depend on what happens to be installed on the machine.
    ok, reason = (
        (True, "launcher supplied by the caller") if popen else executor.available()
    )
    if not ok:
        localstate.append_event(
            paths, "worker_unavailable", run_id=run_id, harness=executor.name
        )
        return {
            "ok": False,
            "outcome": "harness_unavailable",
            "run_id": run_id,
            "role": role,
            "model": model,
            "harness": executor.name,
            "provider": executor.provider,
            "reason": reason,
            "returncode": None,
            "turns": 0,
            "elapsed_seconds": 0.0,
            "usage": {},
            "cost_usd": 0.0,
            "cost_known": False,
            "last_action": "",
            "events": [],
            "pid": None,
        }

    command = executor.command(model, role, worktree, budget, prompt)
    timeout = int(budget.get("timeout_seconds", 900))
    started = time.monotonic()

    localstate.append_event(
        paths,
        "worker_started",
        run_id=run_id,
        role=role,
        model=model,
        harness=executor.name,
        provider=executor.provider,
        worktree=str(worktree),
    )

    spawn = popen or subprocess.Popen
    process = spawn(
        command,
        cwd=str(worktree),
        env=executor.env(os.environ, run_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    if on_spawn is not None and getattr(process, "pid", None):
        on_spawn(int(process.pid))

    lines: list[str] = []
    last_action = ""
    turns = 0
    timed_out = False
    stream_path = run_dir / "stdout.jsonl"

    with stream_path.open("a", encoding="utf-8", newline="\n") as stream:
        for line in process.stdout or []:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            lines.append(line)
            stream.write(str(localstate.redact(line)) + "\n")
            stream.flush()
            if time.monotonic() - started >= timeout:
                timed_out = True
                process.kill()
                break

    stderr = ""
    try:
        _, stderr = process.communicate(timeout=60)
    except Exception:  # noqa: BLE001 - a hung child must not hang the runtime
        process.kill()
    if stderr:
        (run_dir / "stderr.log").write_text(
            str(localstate.redact(stderr)), encoding="utf-8"
        )

    events = parse_events(lines)
    result_event: dict[str, Any] = {}
    for event in events:
        kind = str(event.get("type") or event.get("event") or "")
        if kind in ("assistant", "message", "step"):
            turns += 1
            text = _text_of(event)
            if text:
                last_action = text
        elif kind in ("result", "done", "finish", "summary"):
            result_event = event
        elif _text_of(event):
            last_action = _text_of(event) or last_action

    returncode = process.returncode if process.returncode is not None else -1
    subtype = str(result_event.get("subtype") or result_event.get("status") or "")
    ok_run = (
        (not timed_out)
        and returncode == 0
        and subtype in ("", "success", "completed", "ok")
    )
    outcome = "timeout" if timed_out else ("completed" if ok_run else "failed")

    # A subscription reports a notional figure rather than a billed one, so the
    # runtime records whether the number means money before recording the
    # number. Inventing a subscription cost would be worse than showing none.
    cost = _cost_of(result_event)
    cost_known = bool(cost) and executor.provider != "anthropic"

    run_record = {
        "ok": ok_run,
        "outcome": outcome,
        "run_id": run_id,
        "role": role,
        "model": model,
        "harness": executor.name,
        "provider": executor.provider,
        "returncode": returncode,
        "turns": turns,
        "elapsed_seconds": round(time.monotonic() - started, 1),
        "pid": getattr(process, "pid", None),
        "stop_reason": result_event.get("stop_reason") or subtype or None,
        "session_id": result_event.get("session_id") or result_event.get("sessionID"),
        "usage": _usage_of(result_event),
        "cost_usd": cost,
        "cost_known": cost_known,
        "last_action": last_action,
        "stream": str(stream_path),
        "events": events[-5:],
    }
    localstate.write(run_dir / "result.json", run_record)
    localstate.append_event(
        paths,
        "worker_finished",
        run_id=run_id,
        role=role,
        harness=executor.name,
        outcome=outcome,
        turns=turns,
    )
    return run_record


def worker_image(executor: Executor | None = None) -> str:
    """The process image a recorded pid should still be running."""
    name = getattr(executor, "name", "claude-cli")
    base = "opencode" if name == "opencode" else "claude"
    return f"{base}.exe" if sys.platform == "win32" else base
