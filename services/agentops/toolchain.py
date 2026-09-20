"""The tools verification runs with, and the lock that keeps them apart.

Two local problems, both of which produce a green result that means nothing.

The first is uv. `pyproject.toml` pins an exact version, and the uv on this
workstation's PATH is not it. Running the wrong one either refuses outright or
resolves a different dependency set than CI, so the binary is discovered and
version-checked rather than assumed. The pinned binary usually exists somewhere
on the machine already -- it is fetched per checkout and gitignored -- so
discovery looks through the other worktrees before giving up, and the path it
finds is cached in ignored local configuration. It is never committed: it is
true of this machine, not of the repository.

The second is ports. Everything except the pure-Python suite binds something
fixed: the smoke suite starts a web server, and the infrastructure scripts
start Supabase and MinIO on hard-coded ports. Two workers running those at once
do not conflict politely; they interleave and produce a failure that is about
the collision rather than about the code. One cross-process lock serialises
exactly those, and nothing else.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from services.agentops import localstate

UV_ENV_OVERRIDE = "SHOULDER_UV_PATH"
LOCK_NAME = "infra.lock"
# Scheduling is a separate lock from verification on purpose: a gated run
# holds the infrastructure lock for many minutes, and blocking every
# scheduling decision behind it would serialise the whole runtime.
SCHEDULE_LOCK_NAME = "schedule.lock"
DEFAULT_LOCK_TTL_SECONDS = 5400

# Every check that binds a fixed port or starts a container. `check.ps1` is on
# the list because its smoke step starts a web server, which is a port even
# though it is not Docker.
GATED_SCRIPT = re.compile(r"scripts[\\/]check(-[a-z-]+)?\.ps1$", re.IGNORECASE)


class UvUnavailable(RuntimeError):
    """No uv on this machine satisfies the repository pin."""


class LockBusy(RuntimeError):
    """Another process holds the infrastructure lock and is still alive."""


def required_version(root: Path) -> str:
    """The exact uv version `pyproject.toml` demands."""
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'required-version\s*=\s*"==\s*([0-9][^"\s]*)"', text)
    if not match:
        raise UvUnavailable("pyproject.toml does not pin required-version for uv")
    return match.group(1)


def _binary_names() -> tuple[str, ...]:
    return ("uv.exe", "uv") if sys.platform == "win32" else ("uv",)


def _tools_binaries(directory: Path) -> Iterator[Path]:
    for name in _binary_names():
        candidate = directory / ".tools" / name
        if candidate.exists():
            yield candidate


def _worktree_roots(root: Path) -> list[Path]:
    """Every checkout of this repository this machine knows about.

    The pinned binary is gitignored, so a fresh worktree never has it while the
    checkout next door does. Asking Git is how the copy is found without
    committing the path to it.
    """
    roots: list[Path] = []
    try:
        listed = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return roots
    for line in (listed.stdout or "").splitlines():
        if line.startswith("worktree "):
            roots.append(Path(line[len("worktree ") :].strip()))
    return roots


def candidates(root: Path, config: dict[str, Any]) -> list[tuple[str, Path]]:
    """Where to look for uv, best evidence first.

    Explicit beats discovered, and discovered beats PATH: the PATH entry is the
    one most likely to be a different version than the repository wants.
    """
    found: list[tuple[str, Path]] = []
    seen: set[str] = set()

    def offer(source: str, path: Path | None) -> None:
        if path is None:
            return
        key = str(path).lower()
        if key in seen:
            return
        seen.add(key)
        found.append((source, path))

    override = os.environ.get(UV_ENV_OVERRIDE, "").strip()
    if override:
        offer(f"${UV_ENV_OVERRIDE}", Path(override))

    configured = str(config.get("uv_path") or "").strip()
    if configured:
        offer("config.json uv_path", Path(configured))

    for path in _tools_binaries(root):
        offer("repository .tools", path)

    for worktree in _worktree_roots(root):
        if worktree.resolve() == root.resolve():
            continue
        for path in _tools_binaries(worktree):
            offer(f"worktree {worktree.name}", path)

    for name in _binary_names():
        from shutil import which

        located = which(name)
        if located:
            offer("PATH", Path(located))
    return found


def _probe(path: Path) -> str:
    result = subprocess.run(
        [str(path), "--version"],
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    return (result.stdout or result.stderr or "").strip()


def _version_of(output: str) -> str:
    match = re.search(r"\b(\d+\.\d+\.\d+)\b", output or "")
    return match.group(1) if match else ""


# PowerShell 7 first, because that is what CI runs and what the scripts are
# written against, then the Windows PowerShell every Windows machine already
# has. Naming only `pwsh` assumed an install that is not standard anywhere:
# this workstation has 5.1 and no `pwsh`, so the gated verification could not
# start at all, and because a missing executable raises rather than returning
# a failing exit code it took the whole project loop down with it -- after the
# task had been implemented, verified and reviewed.
POWERSHELL_NAMES = ("pwsh", "powershell")


def powershell() -> str:
    """The PowerShell this machine actually has.

    Falls back to the first name when neither resolves, so the caller fails on
    the command it meant to run and says which one was missing.
    """
    for name in POWERSHELL_NAMES:
        found = shutil.which(name)
        if found:
            return found
    return POWERSHELL_NAMES[0]


def resolve_uv(
    root: Path,
    paths: localstate.LocalPaths,
    *,
    probe: Callable[[Path], str] | None = None,
) -> Path:
    """The uv binary to run, proven to match the pin before it is returned."""
    pin = required_version(root)
    config = localstate.load_config(paths)
    ask = probe or _probe
    tried: list[str] = []

    for source, path in candidates(root, config):
        if not path.exists():
            tried.append(f"{source}: {path} (missing)")
            continue
        version = _version_of(ask(path))
        if version == pin:
            if str(config.get("uv_path") or "") != str(path):
                config["uv_path"] = str(path)
                localstate.save_config(paths, config)
            return path
        tried.append(f"{source}: {path} (uv {version or 'unreadable'})")

    raise UvUnavailable(
        f"no uv {pin} found. Tried: "
        + ("; ".join(tried) if tried else "nothing")
        + f". Fix it by setting {UV_ENV_OVERRIDE} to a uv {pin} binary, "
        f"or by placing one at .tools/uv{'.exe' if sys.platform == 'win32' else ''}."
    )


def needs_infra_lock(command: list[str]) -> bool:
    """Whether this command contends for a fixed port or a container.

    Serialising everything would make two workers strictly sequential and
    remove the point of running two. Only the checks that share a real machine
    resource are gated.
    """
    return any(GATED_SCRIPT.search(str(part)) for part in command)


def _lock_is_stale(holder: dict[str, Any], ttl_seconds: int) -> tuple[bool, str]:
    """Whether the recorded holder has provably stopped or overrun its ceiling.

    Unreadable metadata fails closed. A live holder whose record is missing or
    malformed used to be classified stale, which let a second verification
    start on the same ports while the first was still running.
    """
    raw = str(holder.get("pid") or "")
    if not raw.isdigit():
        return False, "holder record is unreadable; refusing to take the lock"
    pid = int(raw)
    if not localstate.process_alive(pid, holder.get("image")):
        return True, f"owner pid {raw} is gone"
    started = holder.get("started_at")
    try:
        began = datetime.fromisoformat(str(started))
    except (TypeError, ValueError):
        return False, "owner is alive but recorded no usable start time"
    if began.tzinfo is None:
        began = began.replace(tzinfo=UTC)
    if datetime.now(UTC) - began > timedelta(seconds=ttl_seconds):
        return True, f"owner held the lock past {ttl_seconds}s"
    return False, ""


def _publish(lock_path: Path, payload: dict[str, Any]) -> bool:
    """Make the lock appear complete or not at all.

    Creating the file and then writing it leaves a window where another
    process reads `{}`, decides the holder is dead, and takes the lock. The
    payload is written to a private file first and linked into place, so the
    name only ever appears with its contents already there.
    """
    staging = lock_path.with_name(f"{lock_path.name}.{uuid.uuid4().hex}.staging")
    staging.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    try:
        os.link(staging, lock_path)
        return True
    except FileExistsError:
        return False
    except OSError:
        # A filesystem without hard links: fall back to exclusive create, which
        # is still atomic for the name even though the content lands after.
        try:
            handle = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(payload, indent=2, sort_keys=True))
        return True
    finally:
        staging.unlink(missing_ok=True)


def _take_from_stale(lock_path: Path, token: str) -> bool:
    """Claim the right to replace a stale lock, atomically.

    Two processes can both decide a lock is stale. Whoever renames it away
    wins; the loser finds nothing to rename and retries against whatever is
    there now. Without this both would unlink and both would claim.
    """
    reserved = lock_path.with_name(f"{lock_path.name}.stale.{token}")
    try:
        os.rename(lock_path, reserved)
    except OSError:
        return False
    reserved.unlink(missing_ok=True)
    return True


@contextmanager
def file_lock(
    paths: localstate.LocalPaths,
    *,
    owner: str,
    name: str = LOCK_NAME,
    ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS,
) -> Iterator[dict[str, Any]]:
    """Hold the one lock that shared-port verification runs under.

    At most one process owns it at a time. A crashed holder must not block the
    machine forever, so a lock whose owner has provably stopped -- or which has
    been held past the ceiling -- can be taken; the takeover is recorded rather
    than silent. Release only removes a lock that is still ours, so a process
    that overran its TTL cannot delete its successor's lock on the way out.
    """
    localstate.ensure(paths)
    lock_path = paths.locks / name
    token = uuid.uuid4().hex
    payload: dict[str, Any] = {
        "owner": owner,
        "token": token,
        "pid": os.getpid(),
        "image": Path(sys.executable).name,
        "host": os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "",
        "started_at": localstate.now(),
        "recovered": False,
    }

    if not _publish(lock_path, payload):
        holder = localstate.read(lock_path, {})
        stale, why = _lock_is_stale(holder, ttl_seconds)
        if not stale:
            raise LockBusy(
                f"{name} is held by {holder.get('owner')} "
                f"(pid {holder.get('pid')}, since {holder.get('started_at')}): {why}"
                if why
                else f"{name} is held by {holder.get('owner')} "
                f"(pid {holder.get('pid')}, since {holder.get('started_at')})"
            )
        payload["recovered"] = True
        payload["recovered_from"] = {
            "owner": holder.get("owner"),
            "pid": holder.get("pid"),
            "started_at": holder.get("started_at"),
            "reason": why,
        }
        if not _take_from_stale(lock_path, token) or not _publish(lock_path, payload):
            raise LockBusy(
                f"another process claimed {name} while this one was recovering it"
            )
        localstate.append_event(paths, "infra_lock_recovered", owner=owner, reason=why)

    try:
        yield payload
    finally:
        # Only ever release our own lock. An overrunning holder that deleted
        # whatever it found would remove its successor's claim and let a third
        # verification start alongside the second.
        current = localstate.read(lock_path, {})
        if str(current.get("token") or "") == token:
            lock_path.unlink(missing_ok=True)


def fast_check_commands(uv: Path) -> list[list[str]]:
    """The checks that need no shared resource, in the order CI runs them."""
    return [
        [str(uv), "run", "--locked", "ruff", "format", "--check", "."],
        [str(uv), "run", "--locked", "ruff", "check", "."],
        [str(uv), "run", "--locked", "mypy"],
        [
            str(uv),
            "run",
            "--locked",
            "python",
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests",
            "-p",
            "test_*.py",
        ],
    ]


def run_commands(
    root: Path,
    commands: list[list[str]],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    timeout: int = 3600,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Run checks in order, stopping at the first failure."""
    execute = runner or subprocess.run
    steps: list[dict[str, Any]] = []
    for command in commands:
        try:
            result = execute(
                command,
                cwd=str(root),
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
                # None means inherit, which is what every caller but the gated
                # verification wants.
                env=dict(env) if env is not None else None,
            )
        except OSError as problem:
            # A tool that is not installed raises rather than returning an
            # exit code, and this runs on a worker thread, so the exception
            # came back out of the future and ended the whole project loop --
            # a task that was implemented, verified and reviewed was lost to a
            # missing `pwsh`. A check that cannot start is a check that
            # failed, and it names what was missing.
            steps.append(
                {
                    "command": command,
                    "returncode": -1,
                    "tail": [f"could not start {command[0]}: {problem}"],
                }
            )
            return {"ok": False, "steps": steps, "failed": command}
        tail = ((result.stdout or "") + (result.stderr or "")).strip().splitlines()
        steps.append(
            {
                "command": command,
                "returncode": result.returncode,
                "tail": tail[-20:],
            }
        )
        if result.returncode != 0:
            return {"ok": False, "steps": steps, "failed": command}
    return {"ok": True, "steps": steps, "failed": None}


@contextmanager
def infra_lock(
    paths: localstate.LocalPaths,
    *,
    owner: str,
    ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS,
) -> Iterator[dict[str, Any]]:
    """The lock shared-port verification runs under."""
    with file_lock(paths, owner=owner, name=LOCK_NAME, ttl_seconds=ttl_seconds) as held:
        yield held


@contextmanager
def schedule_lock(
    paths: localstate.LocalPaths, *, owner: str, ttl_seconds: int = 300
) -> Iterator[dict[str, Any]]:
    """The lock a coordinator holds while it decides and claims a task.

    Loading the ledger, acquiring in memory and writing it back is not atomic
    across processes: two coordinators could each read no lease, each pass the
    writer cap against its own stale snapshot, and each start a worker on the
    same branch. It is held only for the decision, never for the work.
    """
    with file_lock(
        paths, owner=owner, name=SCHEDULE_LOCK_NAME, ttl_seconds=ttl_seconds
    ) as held:
        yield held
