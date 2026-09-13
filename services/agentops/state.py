"""Durable orchestrator state.

Git and GitHub are the source of truth for this system, not a conversation. A
replacement worker reconstructs everything it needs from these files plus the
repository itself, so every field a handover depends on lives here rather than
in prose.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

OPS_DIR = "ops"
STATE_DIR = f"{OPS_DIR}/state"


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def policy(self) -> Path:
        return self.root / OPS_DIR / "policy.json"

    @property
    def progress(self) -> Path:
        return self.root / STATE_DIR / "progress.json"

    @property
    def models(self) -> Path:
        return self.root / STATE_DIR / "models.json"

    @property
    def providers(self) -> Path:
        return self.root / STATE_DIR / "providers.json"

    @property
    def tasks(self) -> Path:
        return self.root / STATE_DIR / "tasks.json"

    @property
    def budget(self) -> Path:
        return self.root / STATE_DIR / "budget.json"


def read_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        if default is None:
            raise FileNotFoundError(path)
        return dict(default)
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    """Write state with LF endings on every platform.

    Default text mode translates to CRLF on Windows, and the repository
    formatter rejects that, so a coordinator run on a workstation would break
    the quality gate it exists to protect.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(data, indent=2, sort_keys=True) + "\n"
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(body)


def load_policy(paths: Paths) -> dict[str, Any]:
    """Load policy, letting the AUTONOMY_ENABLED variable override the file.

    The repository variable is the emergency stop: it changes behaviour without
    a commit, so autonomy can be halted even when no one can land a change.
    """
    policy = read_json(paths.policy)
    override = os.environ.get("AUTONOMY_ENABLED")
    if override is not None:
        policy["autonomy"]["enabled"] = override.strip().lower() in ("1", "true", "yes")
        policy["autonomy"]["source"] = "AUTONOMY_ENABLED environment variable"
    return policy


def autonomy_enabled(policy: dict[str, Any]) -> bool:
    return bool(policy["autonomy"]["enabled"])


# --- progress ledger -------------------------------------------------------


def completed_tasks(progress: dict[str, Any]) -> set[int]:
    return {int(t) for t in progress.get("completed_tasks", [])}


def dependencies_satisfied(
    progress: dict[str, Any], prerequisites: tuple[int, ...]
) -> tuple[bool, list[int]]:
    done = completed_tasks(progress)
    missing = sorted(p for p in prerequisites if p not in done)
    return (not missing), missing


def gate_passed(progress: dict[str, Any], name: str = "real_use_gate") -> bool:
    return bool(progress.get("gates", {}).get(name, False))


# --- provider health -------------------------------------------------------

DEFAULT_HEALTH = "AVAILABLE"


def provider_health(providers: dict[str, Any]) -> dict[str, str]:
    """Current health per lane, expiring any cooldown whose reset has passed."""
    out: dict[str, str] = {}
    current = datetime.now(UTC)
    for lane, record in providers.get("lanes", {}).items():
        status = record.get("status", DEFAULT_HEALTH)
        reset = record.get("reset_at")
        if status == "COOLDOWN" and reset:
            try:
                if datetime.fromisoformat(reset) <= current:
                    # The window has legitimately reset. The lane returns to the
                    # pool only after a health check, so it is DEGRADED, not
                    # AVAILABLE, until one succeeds.
                    status = "DEGRADED"
            except ValueError:
                pass
        out[lane] = status
    return out


def qualified_lanes(providers: dict[str, Any]) -> frozenset[str]:
    """Lanes proven to work end to end.

    Used for lanes whose model cannot be selected, where qualifying one model
    proves nothing about what the account actually runs. The proof is a real
    round trip through the lane, recorded by `cli qualify-lane`.
    """
    return frozenset(
        lane
        for lane, record in providers.get("lanes", {}).items()
        if record.get("lane_qualified")
    )


def mark_lane_qualified(
    providers: dict[str, Any], lane: str, *, evidence: str
) -> dict[str, Any]:
    record = providers.setdefault("lanes", {}).setdefault(lane, {})
    record["lane_qualified"] = True
    record["lane_qualified_at"] = now()
    record["lane_qualification_evidence"] = evidence
    return providers


def mark_provider(
    providers: dict[str, Any],
    lane: str,
    status: str,
    *,
    reason: str = "",
    reset_at: str | None = None,
) -> dict[str, Any]:
    lanes = providers.setdefault("lanes", {})
    record = lanes.setdefault(lane, {})
    previous = record.get("status", DEFAULT_HEALTH)
    record["status"] = status
    record["reason"] = reason
    record["changed_at"] = now()
    if reset_at:
        record["reset_at"] = reset_at
    elif status in ("AVAILABLE", "DEGRADED"):
        record.pop("reset_at", None)
    if status == DEFAULT_HEALTH:
        record["last_success"] = now()
        record["failure_count"] = 0
    elif status != previous:
        record["failure_count"] = int(record.get("failure_count", 0)) + 1
    return providers


# --- budget ----------------------------------------------------------------


def _period_keys() -> tuple[str, str]:
    current = datetime.now(UTC)
    return current.strftime("%Y-%m-%d"), current.strftime("%Y-%m")


def budget_blocked(policy: dict[str, Any], budget: dict[str, Any]) -> frozenset[str]:
    """Lanes whose daily or monthly API spend ceiling is already reached."""
    day, month = _period_keys()
    spend = budget.get("spend", {})
    limits = policy["budget"]
    blocked = set()
    for lane, key in (("openrouter", "openrouter"), ("codex_api", "openai")):
        daily = float(spend.get("daily", {}).get(day, {}).get(lane, 0.0))
        monthly = float(spend.get("monthly", {}).get(month, {}).get(lane, 0.0))
        if daily >= float(limits[f"{key}_daily_usd"]):
            blocked.add(lane)
        elif monthly >= float(limits[f"{key}_monthly_usd"]):
            blocked.add(lane)
    return frozenset(blocked)


def record_spend(
    budget: dict[str, Any], lane: str, usd: float, *, task_id: int | None = None
) -> dict[str, Any]:
    """Add spend to the daily, monthly, and per-task buckets.

    A provider-reported cost is untrusted input. A negative, NaN, or infinite
    amount would lower a running total or make every ceiling comparison false,
    which turns budget enforcement off rather than tripping it.
    """
    amount = float(usd)
    if not math.isfinite(amount) or amount < 0:
        raise ValueError(f"refusing to record a spend of {usd!r}")
    usd = amount
    day, month = _period_keys()
    spend = budget.setdefault("spend", {})
    for bucket, key in (("daily", day), ("monthly", month)):
        period = spend.setdefault(bucket, {}).setdefault(key, {})
        period[lane] = round(float(period.get(lane, 0.0)) + float(usd), 6)
    if task_id is not None:
        tasks = spend.setdefault("per_task", {}).setdefault(str(task_id), {})
        tasks[lane] = round(float(tasks.get(lane, 0.0)) + float(usd), 6)
    budget["updated_at"] = now()
    return budget


def task_spend(budget: dict[str, Any], task_id: int) -> float:
    """Total recorded across every lane for one task."""
    recorded = budget.get("spend", {}).get("per_task", {}).get(str(task_id), {})
    return round(sum(float(v) for v in recorded.values()), 6)


def task_budget_exceeded(
    policy: dict[str, Any], budget: dict[str, Any], task_id: int
) -> bool:
    """Whether this task has already used its own ceiling.

    Checked before dispatch as well as during a run, so a task that burned its
    allowance across several attempts is not handed another worker.
    """
    ceiling = float(policy["budget"].get("per_task_usd", 0.0))
    if ceiling <= 0:
        return False
    return task_spend(budget, task_id) >= ceiling
