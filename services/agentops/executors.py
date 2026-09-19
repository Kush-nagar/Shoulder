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
* Codex CLI 0.154.0: `codex exec --json` emits JSONL whose shapes were read off
  the installed binary rather than assumed. `-m` selects the model and
  `-c model_reasoning_effort=<effort>` the effort, so unlike the cloud mention
  lane this one really is model-enforced; `low`, `medium`, `high` and `xhigh`
  are all accepted. `--ignore-user-config` drops the workstation's MCP servers
  and hooks while keeping the ChatGPT subscription auth, which is what makes a
  worker reproducible. A turn ends at `turn.completed` or `turn.failed`, and
  the exit code agrees with it.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
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
CODEX_BINARY = os.environ.get("SHOULDER_CODEX_BINARY", "codex")

# How OpenCode names a model routed through OpenRouter: its provider id, then
# the OpenRouter model id, which is itself `vendor/model`.
OPENCODE_PROVIDER = "openrouter"

# Lanes driven by the local Codex CLI. Named here so policy and code cannot
# drift: `codex_cloud` is the mention lane and is NOT one of these.
CODEX_LOCAL_LANES = ("codex_local",)

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
    # Codex wraps everything it says in `item.completed`, so the readable
    # part is one level down and has no `content` at all.
    item = event.get("item")
    if isinstance(item, Mapping):
        if isinstance(item.get("text"), str) and item["text"].strip():
            return str(item["text"]).strip()[:400]
        kind = str(item.get("type") or "")
        if kind and kind != "agent_message":
            label = item.get("command") or item.get("path") or kind
            return f"tool: {str(label)[:200]}"

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


def terminate_tree(process: Any) -> None:
    """Stop the worker and anything it started.

    Killing only the harness leaves its children -- a shell, a test runner, a
    language server -- editing the worktree after the coordinator has already
    declared the task timed out. On Windows the job is done by `taskkill /T`,
    since there is no process group to signal.
    """
    pid = getattr(process, "pid", None)
    if sys.platform == "win32" and pid:
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                check=False,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        process.kill()
    except Exception:  # noqa: BLE001 - it may already be gone
        pass


def _usage_of(event: Mapping[str, Any]) -> dict[str, Any]:
    usage = event.get("usage") or event.get("tokens")
    return dict(usage) if isinstance(usage, Mapping) else {}


def _cost_of(event: Mapping[str, Any]) -> float:
    for key in ("total_cost_usd", "cost_usd", "cost"):
        value = event.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return 0.0


# What a harness says when the account's allowance, not the code, is what
# stopped it. Deliberately narrow: these are allowance sentences, not the word
# "limit", so a failing test that happens to print "rate limit" in application
# output is still an implementation failure and still spends a repair attempt.
EXHAUSTION_MARKERS = (
    "session limit",
    "usage limit",
    "weekly limit",
    "5-hour limit",
    "five-hour limit",
    "allowance has been exhausted",
    "allowance is exhausted",
    "quota exceeded",
    "insufficient credits",
    "insufficient_quota",
)

# An explicit reset instant, when the harness prints one. Only a machine
# readable timestamp is trusted: "resets at 3pm" has no date and no zone, and
# guessing one would put a lane back in the pool at the wrong hour. Without it
# the caller falls back to the lane's declared usage window, which is what the
# cloud path already does for Codex.
RESET_PATTERN = re.compile(
    r"reset(?:s|s at|ting at|_at)?[\s:\"']+"
    r"(\d{4}-\d{2}-\d{2}[T ][\d:]{5,8}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)",
    re.IGNORECASE,
)


# Where the harness itself speaks, as opposed to where it relays what a model
# wrote. Only these are searched.
# `turn.failed` is where Codex puts its refusal, so it has to be searched for
# an allowance message. Its benign advisories are NOT here: those arrive as
# `item.completed` carrying an `error` item -- a clamped hook timeout, a
# shortened skill description -- and reading those as harness failures would
# fail every Codex run that ever emitted one.
RESULT_EVENT_TYPES = (
    "result",
    "done",
    "finish",
    "error",
    "summary",
    "turn.completed",
    "turn.failed",
)
ERROR_FIELDS = ("error", "message", "detail", "reason", "subtype", "stop_reason")


def _harness_error_text(run: Mapping[str, Any]) -> str:
    """What the harness said about why it stopped, and nothing else.

    Deliberately not `last_action`, and not every event. Those carry whatever
    the model wrote and whatever a file it read contained, so a task whose own
    diff or test output mentions a usage limit would have been read as an
    exhausted account -- parking a healthy provider and skipping the repair the
    task actually needed.

    The cost of this narrowing is the opposite error: an allowance message that
    appears only as assistant prose is treated as an ordinary failure and goes
    through ordinary repair. That is the right way round. A missed failover
    wastes one attempt; a false one takes a working provider out of service and
    leaves a real defect unfixed.
    """
    parts = [str(run.get("stderr") or ""), str(run.get("stop_reason") or "")]
    if run.get("outcome") == "harness_unavailable":
        parts.append(str(run.get("reason") or ""))
    for event in run.get("events") or []:
        if not isinstance(event, Mapping):
            continue
        kind = str(event.get("type") or event.get("event") or "").lower()
        is_error = bool(event.get("is_error")) or kind == "error"
        subtype = str(event.get("subtype") or "").lower()
        if kind not in RESULT_EVENT_TYPES and not is_error:
            continue
        # `result` is the final text, which on a successful run is the model's
        # own prose. It is read only when the event says it is an error, where
        # the harness has put its refusal instead.
        fields = ERROR_FIELDS + (("result",) if is_error or "error" in subtype else ())
        for field in fields:
            value = event.get(field)
            if isinstance(value, str):
                parts.append(value)
            elif isinstance(value, Mapping):
                try:
                    parts.append(json.dumps(value))
                except (TypeError, ValueError):
                    pass
    return " ".join(parts).lower()


def exhaustion(run: Mapping[str, Any]) -> dict[str, Any] | None:
    """Whether this run stopped because the provider allowance ran out.

    This is a different fact from "the work failed", and conflating them is
    expensive in both directions: charging a task's repair budget for an empty
    subscription burns attempts on a task that was never wrong, while treating
    a genuine failure as exhaustion would park a healthy lane and never fix the
    code. So the answer is None unless the harness actually said so.
    """
    if run.get("ok"):
        return None
    text = _harness_error_text(run)
    marker = next((m for m in EXHAUSTION_MARKERS if m in text), None)
    if marker is None:
        return None
    found = RESET_PATTERN.search(text)
    return {
        "exhausted": True,
        "marker": marker,
        "reset_at": found.group(1).upper() if found else "",
        "harness": run.get("harness", ""),
        "provider": run.get("provider", ""),
    }


class Executor(Protocol):
    """One way to run a coding worker."""

    name: str
    provider: str
    # Whether the prompt is delivered on stdin rather than as the last
    # argument. It has to be, for anything but a short one: Windows caps a
    # command line at 32767 characters and a review prompt carries up to 60000
    # characters of diff, so argv delivery fails outright with
    # "[WinError 206] The filename or extension is too long".
    prompt_on_stdin: bool

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
    # Left on argv, which is how this lane has always run. It shares the
    # Windows command-line ceiling described on the protocol, so a very large
    # review prompt will fail here until this lane is moved to stdin too --
    # that is a change to a working, well-covered path and wants its own
    # verification against the installed CLI rather than being assumed.
    prompt_on_stdin = False

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
        # A reviewer runs in plan mode, which cannot write.
        #
        # A writable worker runs in bypass mode, and the reason is the runtime
        # rather than a preference. `acceptEdits` approves edits and nothing
        # else: `uv`, `pnpm`, `alembic`, `pytest` and `scripts/check.ps1` still
        # raise a permission prompt, and with `--permission-prompts none` and
        # no terminal attached there is nobody to answer it, so every command
        # the task actually needs is denied. The worker edits files it can
        # never verify. This runtime is unattended by design, so the bypass is
        # explicit here instead of being half-configured elsewhere.
        argv = [
            self.binary,
            "-p",
            "--model",
            model,
            "--output-format",
            "stream-json",
            "--verbose",
        ]
        if role in READ_ONLY_ROLES:
            argv += ["--permission-mode", "plan", "--permission-prompts", "none"]
        else:
            argv += ["--dangerously-skip-permissions"]
        argv += ["--max-turns", str(int(budget.get("max_turns", 20)))]
        return argv

    def env(self, base: Mapping[str, str], run_dir: Path) -> dict[str, str]:
        """The subscription session's environment, with another lane's key out.

        A writable worker can read its own environment. There is no reason for
        a Claude worker to be able to read the OpenRouter credential, so it is
        removed rather than inherited.
        """
        env = dict(base)
        for name in (OPENROUTER_KEY_ENV, "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
            env.pop(name, None)
        return env

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
    # OpenCode's published documentation does not specify stdin behaviour for
    # `opencode run`, and guessing would swap a failure that is loud for one
    # that is silent.
    prompt_on_stdin = False

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


class CodexCliExecutor:
    """The Codex CLI against the ChatGPT subscription, on this machine.

    The local counterpart of the `codex_cloud` mention lane, and materially
    different from it in the one way that matters to routing: a mention carries
    no model and no reasoning effort, while `codex exec` takes both as
    arguments. So this lane is model-enforced and the tier the router chose is
    actually applied rather than merely recorded.

    `--ignore-user-config` is not a detail. Without it a worker inherits this
    workstation's `~/.codex/config.toml`: its MCP servers (which log
    authentication failures into the run and can reach the network), its hooks,
    and whatever model the human last selected. A worker whose behaviour
    depends on a file nobody reviewed is not reproducible, and the tier the
    router applied would be silently overridden. Authentication is unaffected,
    because Codex reads credentials from `CODEX_HOME` rather than from the
    config file.
    """

    name = "codex-cli"
    provider = "openai"
    # `codex exec -` reads the instructions from stdin; verified against the
    # installed CLI, not inferred. This is what makes a real review possible
    # here: the prompt carries the diff, and on Windows that is far past what
    # a command line can hold.
    prompt_on_stdin = True

    def __init__(self, binary: str | None = None, effort: str = "") -> None:
        self.binary = binary or CODEX_BINARY
        # The router's decision, applied. Empty means "whatever the account
        # defaults to", which is the honest reading when nobody chose.
        self.effort = effort

    def available(self) -> tuple[bool, str]:
        found = shutil.which(self.binary)
        if not found:
            return False, (
                f"{self.binary} is not installed. One-time install: "
                "npm install -g @openai/codex, then `codex login`"
            )
        return True, f"{found}"

    def argv(
        self, model: str, role: str, worktree: Path, budget: Mapping[str, int]
    ) -> list[str]:
        argv = [
            self.binary,
            "exec",
            "--json",
            "--ignore-user-config",
            "-C",
            str(worktree),
        ]
        # A lane that cannot be told which model to use reports
        # "account-configured" rather than a slug. Passing that string to `-m`
        # would ask Codex for a model of that name, so it is not passed.
        if model and model != "account-configured":
            argv += ["-m", model]
        if self.effort:
            argv += ["-c", f'model_reasoning_effort="{self.effort}"']
        if role in READ_ONLY_ROLES:
            # Codex's own sandbox does the enforcing here, not a prompt.
            argv += ["-s", "read-only"]
        else:
            # The same choice, for the same reason, as the Claude lane's
            # bypass: `workspace-write` still raises an approval prompt for
            # every command outside the workspace and blocks the network, so
            # `uv sync`, `pnpm install` and `scripts/check.ps1` are denied with
            # nobody attached to answer. The worker is already confined to a
            # throwaway worktree on a branch of its own, which is where the
            # real isolation comes from.
            argv += ["--dangerously-bypass-approvals-and-sandbox"]
        return argv

    def env(self, base: Mapping[str, str], run_dir: Path) -> dict[str, str]:
        """The subscription session's environment, with other lanes' keys out.

        A Codex worker has no business reading the OpenRouter or Anthropic
        credentials, so they are removed rather than inherited. `CODEX_HOME` is
        left exactly as it is: it is where the ChatGPT login lives.
        """
        env = dict(base)
        for name in (
            OPENROUTER_KEY_ENV,
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_AUTH_TOKEN",
            "ANTHROPIC_BASE_URL",
        ):
            env.pop(name, None)
        return env

    def command(
        self,
        model: str,
        role: str,
        worktree: Path,
        budget: Mapping[str, int],
        prompt: str,
    ) -> list[str]:
        # `-` means "the instructions arrive on stdin". The prompt itself is
        # deliberately absent from argv; see `prompt_on_stdin`.
        return [*self.argv(model, role, worktree, budget), "-"]


def for_lane(lane: str, harness: str = "", effort: str = "") -> Executor:
    """The harness a lane runs in.

    The lane is the decision the router already made, and the family ban in
    policy keeps Anthropic models in the subscription lane, so a lane is enough
    to decide the harness without re-deciding anything.

    `effort` is carried here rather than through the shared `argv` signature
    because only one harness can act on it. Claude Code and OpenCode have no
    equivalent argument, so giving all three a parameter two of them ignore
    would advertise a setting that does not apply.
    """
    if lane == "openrouter":
        return OpenCodeExecutor()
    if lane in CODEX_LOCAL_LANES:
        return CodexCliExecutor(effort=effort)
    return ClaudeCliExecutor()


def availability() -> dict[str, dict[str, Any]]:
    """What can run here right now, for `doctor` and the dashboard."""
    report: dict[str, dict[str, Any]] = {}
    for executor in (ClaudeCliExecutor(), CodexCliExecutor(), OpenCodeExecutor()):
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
    # The worker gets the prompt as written; the copy kept for observability
    # does not. A diff quoted into a review prompt can carry whatever a worker
    # wrote into a file, and that copy outlives the run.
    (run_dir / "brief.md").write_text(str(localstate.redact(prompt)), encoding="utf-8")

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

    command = list(executor.command(model, role, worktree, budget, prompt))
    # Resolved to a real path before spawning, for every harness. Windows
    # CreateProcess searches PATH but only ever appends `.exe`, so a bare
    # `codex` or `opencode` -- both installed by npm as `.CMD` shims -- fails
    # with "The system cannot find the file specified" even though the harness
    # is installed and `available()` just said so. Only Claude Code escaped it,
    # by happening to install a real `.EXE`.
    if not popen:
        command[0] = shutil.which(command[0]) or command[0]
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

    # Fed from a file rather than written down a pipe. Writing to stdin while
    # reading stdout in the same thread deadlocks as soon as the prompt is
    # bigger than the pipe buffer -- the child blocks writing output nobody is
    # draining, and the parent blocks writing input nobody is reading -- and a
    # review prompt is comfortably bigger than the buffer.
    prompt_file: Path | None = None
    stdin_handle: Any = subprocess.DEVNULL
    if getattr(executor, "prompt_on_stdin", False):
        prompt_file = run_dir / "prompt.txt"
        prompt_file.write_text(prompt, encoding="utf-8")
        stdin_handle = prompt_file.open("rb")

    spawn = popen or subprocess.Popen
    process = spawn(
        command,
        cwd=str(worktree),
        env=executor.env(os.environ, run_dir),
        # Otherwise closed deliberately. Codex appends whatever it finds on
        # stdin to the prompt as a `<stdin>` block, and an inherited terminal
        # would leave an unattended worker waiting for a human who is not there.
        stdin=stdin_handle,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    if stdin_handle is not subprocess.DEVNULL:
        # The child has its own descriptor now. The copy here is closed at
        # once so the file can be removed the moment the run ends.
        stdin_handle.close()

    if on_spawn is not None and getattr(process, "pid", None):
        on_spawn(int(process.pid))

    lines: list[str] = []
    last_action = ""
    turns = 0
    stream_path = run_dir / "stdout.jsonl"

    # The deadline is enforced by a timer, not by the read loop. Checking the
    # clock while iterating stdout only works for a worker that keeps talking:
    # a silent or hung one blocks in the iterator and never reaches the check,
    # so the documented hard stop did not stop anything.
    timed_out = threading.Event()

    def enforce_deadline() -> None:
        timed_out.set()
        terminate_tree(process)

    alarm = threading.Timer(max(1, timeout), enforce_deadline)
    alarm.daemon = True
    alarm.start()

    try:
        with stream_path.open("a", encoding="utf-8", newline="\n") as stream:
            for line in process.stdout or []:
                line = line.rstrip("\n")
                if not line.strip():
                    continue
                lines.append(line)
                stream.write(str(localstate.redact(line)) + "\n")
                stream.flush()
    finally:
        alarm.cancel()

    stderr = ""
    try:
        _, stderr = process.communicate(timeout=60)
    except Exception:  # noqa: BLE001 - a hung child must not hang the runtime
        terminate_tree(process)

    if prompt_file is not None:
        # Removed once the harness has read it and exited. `brief.md` keeps the
        # redacted copy for later; this one is the real text and has no reason
        # to outlive the process that needed it.
        #
        # After the child is gone, not before: it inherited a descriptor on
        # this file for its stdin, and Windows refuses to delete a file another
        # process still holds open -- "[WinError 32] The process cannot access
        # the file because it is being used by another process", which failed
        # the whole run over a temporary file. A worker killed by the timeout
        # can also leave the handle behind, so failing to remove it is logged
        # by leaving it in the run directory rather than raised.
        try:
            prompt_file.unlink(missing_ok=True)
        except OSError:
            pass
    if stderr:
        (run_dir / "stderr.log").write_text(
            str(localstate.redact(stderr)), encoding="utf-8"
        )

    events = parse_events(lines)
    result_event: dict[str, Any] = {}
    # Codex says whether the turn worked in the event stream as well as in the
    # exit code. Both are read: an exit code alone cannot tell a failed turn
    # from a harness that crashed after a good one.
    failed_turn = False
    for event in events:
        kind = str(event.get("type") or event.get("event") or "")
        if kind in ("assistant", "message", "step", "item.completed"):
            turns += 1
            text = _text_of(event)
            if text:
                last_action = text
        elif kind in ("result", "done", "finish", "summary", "turn.completed"):
            result_event = event
        elif kind == "turn.failed":
            result_event = event
            failed_turn = True
        elif _text_of(event):
            last_action = _text_of(event) or last_action

    returncode = process.returncode if process.returncode is not None else -1
    subtype = str(result_event.get("subtype") or result_event.get("status") or "")
    ok_run = (
        (not timed_out.is_set())
        and returncode == 0
        and not failed_turn
        and subtype in ("", "success", "completed", "ok")
    )
    outcome = "timeout" if timed_out.is_set() else ("completed" if ok_run else "failed")

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
        "stop_reason": (
            result_event.get("stop_reason")
            or subtype
            or ("turn.failed" if failed_turn else None)
        ),
        "session_id": result_event.get("session_id") or result_event.get("sessionID"),
        "usage": _usage_of(result_event),
        "cost_usd": cost,
        "cost_known": cost_known,
        "last_action": last_action,
        # Kept on the record, not only in the log file: a provider that refuses
        # for allowance reasons says so here, and the caller has to be able to
        # tell that apart from a failing test. This is the harness's own error
        # channel, which is why it is trusted and `last_action` is not.
        "stderr": stderr[-4000:] if stderr else "",
        "stream": str(stream_path),
        "events": events[-5:],
    }
    # Redacted before it is written and before it is returned: the caller
    # serialises this record to the console, so redacting only on the way to
    # disk still printed a key that a model happened to echo.
    run_record = dict(localstate.redact(run_record))
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
    base = {"opencode": "opencode", "codex-cli": "codex"}.get(name, "claude")
    return f"{base}.exe" if sys.platform == "win32" else base
