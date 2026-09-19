"""Shared fixtures for the orchestration tests.

The model list here is synthetic on purpose. Routing tests must assert policy
behaviour, not whatever the live catalogue happens to contain today.
"""

from __future__ import annotations

import contextlib
import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest import mock

from services.agentops import backlog, catalog

REPO_ROOT = Path(__file__).resolve().parents[1]


def policy() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(
        (REPO_ROOT / "ops" / "policy.json").read_text(encoding="utf-8")
    )
    return loaded


def configured_policy() -> dict[str, Any]:
    """Policy as it looks once the owner has finished account-level setup.

    Lanes whose privacy is enforced on the provider account start ineligible on
    purpose, so tests about anything else have to say they are configured.
    TestAccountLevelPrivacy covers the unconfirmed case.
    """
    settings = policy()
    for lane in settings["lanes"].values():
        if lane.get("requires_privacy_confirmation"):
            lane["privacy_confirmed"] = True
    return settings


def real_backlog() -> backlog.Backlog:
    return backlog.load(REPO_ROOT)


def model(
    model_id: str,
    lane: str,
    *,
    context: int = 400_000,
    price_in: float = 1.0,
    price_out: float = 4.0,
    tools: bool = True,
    reasoning: bool = True,
    vision: bool = False,
    deprecated: bool = False,
) -> catalog.Model:
    return catalog.Model(
        id=model_id,
        lane=lane,
        family=model_id.split("/", 1)[0],
        harness_model=catalog._harness_model(
            model_id, model_id.split("/", 1)[0], catalog.namespace_lanes(policy())
        ),
        context_length=context,
        max_output_tokens=32_000,
        input_usd_per_mtok=price_in,
        output_usd_per_mtok=price_out,
        supports_tools=tools,
        supports_reasoning=reasoning,
        supports_vision=vision,
        supports_structured_output=True,
        deprecated=deprecated,
    )


def model_pool() -> list[catalog.Model]:
    """One cheap, one mid, one strong, one vision model per lane."""
    return [
        # Claude lane -- subscription backed.
        model(
            "anthropic/claude-haiku-4.5",
            "claude_subscription",
            price_in=0.2,
            vision=True,
            context=200_000,
        ),
        model(
            "anthropic/claude-sonnet-5",
            "claude_subscription",
            price_in=1.5,
            vision=True,
            context=1_000_000,
        ),
        model(
            "anthropic/claude-opus-5",
            "claude_subscription",
            price_in=5.0,
            vision=True,
            context=1_000_000,
        ),
        # Codex Cloud -- subscription backed, the only lane allowed to write
        # frontend code.
        model(
            "openai/gpt-5-nano",
            "codex_cloud",
            price_in=0.05,
            vision=True,
            context=400_000,
        ),
        model(
            "openai/gpt-5-mini",
            "codex_cloud",
            price_in=0.25,
            vision=True,
            context=400_000,
        ),
        model(
            "openai/gpt-5.6-luna",
            "codex_cloud",
            price_in=1.2,
            vision=True,
            context=1_000_000,
        ),
        # OpenRouter lane -- cheap backend overflow.
        model(
            "deepseek/deepseek-v4-flash", "openrouter", price_in=0.07, context=1_000_000
        ),
        model(
            "deepseek/deepseek-v4-pro", "openrouter", price_in=1.6, context=1_000_000
        ),
    ]


def qualification(
    models: list[catalog.Model], state: str = "QUALIFIED"
) -> dict[str, str]:
    return {m.id: state for m in models}


def make_stale(lease: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    """Age a lease past the point where it may be reclaimed.

    Staleness needs both conditions: the nominal expiry has passed and nothing
    has heartbeated since. Ageing only the heartbeat leaves a live worker's
    lease intact, which is the behaviour that protects a long harness run.
    """
    from datetime import UTC, datetime, timedelta

    grace = int(settings["lease"]["heartbeat_seconds"]) * int(
        settings["lease"]["stale_after_missed_heartbeats"]
    )
    past = datetime.now(UTC) - timedelta(seconds=grace + 120)
    lease["expires_at"] = past.isoformat(timespec="seconds")
    lease["heartbeat_at"] = past.isoformat(timespec="seconds")
    lease["acquired_at"] = past.isoformat(timespec="seconds")
    return lease


@contextlib.contextmanager
def installed_harnesses(
    *, claude: bool = True, opencode: bool = False, codex: bool = False
) -> Iterator[None]:
    """Pin which coding harnesses look installed.

    Local routing excludes a lane whose harness is not on this machine, which
    is right in production and wrong in a test: the answer would then depend on
    whether the runner happens to have Claude Code or OpenCode installed. CI
    has neither. Tests that care about routing say what is installed.
    """
    real = shutil.which

    def which(name: str, *args: Any, **kwargs: Any) -> str | None:
        base = Path(str(name)).name.lower()
        if base.startswith("claude"):
            return "/usr/bin/claude" if claude else None
        if base.startswith("opencode"):
            return "/usr/bin/opencode" if opencode else None
        if base.startswith("codex"):
            return "/usr/bin/codex" if codex else None
        found: str | None = real(name, *args, **kwargs)
        return found

    with mock.patch.object(shutil, "which", side_effect=which):
        yield
