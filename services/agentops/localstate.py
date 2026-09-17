"""Durable state for the local runtime, kept out of the repository.

The cloud orchestrator treats Git as its source of truth, so its ledger lives in
tracked files. A local run cannot: leases, phases and event streams change many
times a minute, and writing them into `ops/state` would dirty whatever branch a
worker is on and turn ordinary bookkeeping into a diff someone has to review.

So everything mutable here lives under an ignored directory instead. Tracked
`ops/state` is still read, as the baseline a fresh run starts from; it is never
written.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LOCAL_DIR = Path(".agentops") / "local"

# Read at spawn time from the environment and never recorded. Listed here so
# one place decides what must never reach a log, an event, or the dashboard.
SECRET_ENV_NAMES = (
    "OPENROUTER_API_KEY",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "GH_TOKEN",
    "GITHUB_TOKEN",
)

REDACTED = "***"

# Turn and wall-clock ceilings per role. The wall clock is the real stop: the
# CLI accepts --max-turns but does not document it, so it is passed as a hint
# and never trusted as the only bound.
DEFAULT_CONFIG: dict[str, Any] = {
    "$comment": (
        "Local runtime configuration. Ignored by Git: it is machine specific "
        "and may name paths that exist only on this workstation."
    ),
    # Local execution authorisation. Cloud autonomy lives in ops/policy.json
    # and is governance; this is the separate, local, operator-intent switch,
    # and it is why importing a module or loading the dashboard can never
    # start work. Only an explicit local command sets it.
    "local_enabled": False,
    "local_enabled_at": "",
    "local_enabled_by": "",
    "provider": "claude",
    "uv_path": "",
    "worktree_root": "",
    "dashboard": {"host": "127.0.0.1", "port": 4317},
    "roles": {
        "implement": {"max_turns": 120, "timeout_seconds": 5400},
        "review": {"max_turns": 40, "timeout_seconds": 1800},
        "scout": {"max_turns": 12, "timeout_seconds": 600},
        # A tiny writing role for smoke checks and model evaluations. It
        # is not read-only: those tasks prove a worker can change a file.
        "smoke": {"max_turns": 10, "timeout_seconds": 900},
        "summarize": {"max_turns": 6, "timeout_seconds": 300},
    },
}


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class LocalPaths:
    """Where the local runtime keeps its state, relative to the checkout."""

    root: Path

    @property
    def dir(self) -> Path:
        return self.root / LOCAL_DIR

    @property
    def config(self) -> Path:
        return self.dir / "config.json"

    @property
    def runtime(self) -> Path:
        return self.dir / "runtime.json"

    @property
    def workers(self) -> Path:
        return self.dir / "workers.json"

    @property
    def leases(self) -> Path:
        return self.dir / "leases.json"

    @property
    def approvals(self) -> Path:
        return self.dir / "approvals.json"

    @property
    def events(self) -> Path:
        return self.dir / "events.jsonl"

    @property
    def locks(self) -> Path:
        return self.dir / "locks"

    @property
    def runs(self) -> Path:
        return self.dir / "runs"

    def run_dir(self, run_id: str) -> Path:
        return self.runs / run_id


def _secret_values() -> list[str]:
    """The literal secret strings currently in this process's environment."""
    values = []
    for name in SECRET_ENV_NAMES:
        value = os.environ.get(name, "")
        # A one-character value would redact half the alphabet out of every
        # log line, so only redact something long enough to be a real token.
        if len(value.strip()) >= 8:
            values.append(value.strip())
    return values


def redact(value: Any) -> Any:
    """Return `value` with any live secret string replaced.

    Applied on the way in rather than on the way out: a secret that never
    reaches disk cannot leak from disk later.
    """
    secrets = _secret_values()
    if not secrets:
        return value
    return _redact_with(value, secrets)


def _redact_with(value: Any, secrets: list[str]) -> Any:
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, REDACTED)
        return value
    if isinstance(value, Mapping):
        return {k: _redact_with(v, secrets) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_with(v, secrets) for v in value]
    return value


def ensure(paths: LocalPaths) -> LocalPaths:
    """Create the runtime directory tree if it is not there yet."""
    paths.dir.mkdir(parents=True, exist_ok=True)
    paths.locks.mkdir(parents=True, exist_ok=True)
    paths.runs.mkdir(parents=True, exist_ok=True)
    return paths


def read(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return dict(default or {})
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # A half-written file is a crash, not a reason to stop: the caller
        # recovers from Git and the worktrees, which are the real evidence.
        return dict(default or {})
    return loaded if isinstance(loaded, dict) else dict(default or {})


def write(path: Path, data: dict[str, Any]) -> None:
    """Write JSON atomically, so a crash cannot leave a truncated ledger."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(redact(data), indent=2, sort_keys=True) + "\n"
    handle = tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="\n",
        dir=path.parent,
        prefix=path.name,
        suffix=".tmp",
        delete=False,
    )
    try:
        with handle as stream:
            stream.write(payload)
        os.replace(handle.name, path)
    finally:
        if os.path.exists(handle.name):
            os.unlink(handle.name)


def load_config(paths: LocalPaths) -> dict[str, Any]:
    """Configuration with defaults filled in for anything not written yet."""
    stored = read(paths.config, {})
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    config.update({k: v for k, v in stored.items() if k != "roles"})
    for role, budget in (stored.get("roles") or {}).items():
        config["roles"][role] = {**config["roles"].get(role, {}), **budget}
    merged: dict[str, Any] = config
    return merged


def save_config(paths: LocalPaths, config: dict[str, Any]) -> None:
    ensure(paths)
    write(paths.config, config)


def append_event(paths: LocalPaths, kind: str, /, **fields: Any) -> dict[str, Any]:
    """Append one structured event to the stream and return it.

    `kind` is positional-only so a caller may record a field of its own
    called `kind` without colliding with this parameter.
    """
    ensure(paths)
    event: dict[str, Any] = redact({"at": now(), "kind": kind, **fields})
    with paths.events.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(event, sort_keys=True) + "\n")
    return event


def events(paths: LocalPaths, limit: int = 50) -> list[dict[str, Any]]:
    """The most recent events, newest last."""
    if not paths.events.exists():
        return []
    lines = paths.events.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def process_alive(pid: int | None, image: str | None = None) -> bool:
    """Whether `pid` is still running, and is still the process we started.

    `os.kill(pid, 0)` is the usual answer and is wrong here: on Windows
    `os.kill` calls TerminateProcess for every signal but the two console
    events, so the liveness probe would kill the worker it is asking about.
    Windows gets `tasklist` instead.

    `image` guards against pid reuse. An unrelated process that happens to
    have inherited the number is not the worker, and treating it as alive
    would leave a finished task leased forever.
    """
    if not pid or pid <= 0:
        return False
    if sys.platform == "win32":
        return _alive_windows(pid, image)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Running, owned by somebody else.
        return True
    return True


def _alive_windows(pid: int, image: str | None) -> bool:
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return False
    out = (result.stdout or "").strip()
    if not out or "No tasks" in out:
        return False
    if image:
        return image.lower() in out.lower()
    return True


def worker_records(paths: LocalPaths) -> dict[str, Any]:
    records: dict[str, Any] = read(paths.workers, {"workers": {}}).get("workers", {})
    return records


def save_worker(paths: LocalPaths, key: str, record: dict[str, Any]) -> None:
    stored = read(paths.workers, {"workers": {}})
    workers = stored.setdefault("workers", {})
    workers[key] = {**workers.get(key, {}), **record, "updated_at": now()}
    write(paths.workers, stored)


def usage_totals(paths: LocalPaths) -> dict[str, float]:
    """What the local runs have reported, summed.

    On a subscription the cost the harness reports is notional rather than
    billed, so it is labelled as reported cost everywhere it is shown.
    """
    totals = {"reported_cost_usd": 0.0, "input_tokens": 0.0, "output_tokens": 0.0}
    for record in worker_records(paths).values():
        usage = record.get("usage") or {}
        totals["reported_cost_usd"] += float(record.get("cost_usd") or 0.0)
        totals["input_tokens"] += float(usage.get("input_tokens") or 0)
        totals["output_tokens"] += float(usage.get("output_tokens") or 0)
    return totals


def prune_runs(paths: LocalPaths, keep: int = 50) -> list[str]:
    """Drop the oldest run directories, newest `keep` retained."""
    if not paths.runs.exists():
        return []
    dirs = sorted(
        (p for p in paths.runs.iterdir() if p.is_dir()),
        key=lambda p: p.stat().st_mtime,
    )
    removed: list[str] = []
    for path in dirs[: max(0, len(dirs) - keep)]:
        for child in sorted(path.rglob("*"), reverse=True):
            child.unlink() if child.is_file() else child.rmdir()
        path.rmdir()
        removed.append(path.name)
    return removed


def iter_secret_names() -> Iterable[str]:
    return SECRET_ENV_NAMES
