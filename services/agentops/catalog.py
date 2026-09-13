"""Live model capability discovery and qualification state.

Model names are never hard-coded into routing. The orchestrator asks the
provider catalogue what exists right now, normalises the capability metadata,
and routes by capability class. A model that ships next month is picked up
without editing the orchestrator.

One catalogue serves every lane. OpenRouter publishes accurate capability
metadata for the Anthropic and OpenAI families as well as its own, and the
endpoint needs no key, so discovery works before any credential is configured.
Execution still happens in the lane that owns the model: an `anthropic/...`
entry runs through the Claude lane's harness, not through OpenRouter, unless
the OpenRouter lane was chosen explicitly.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

CATALOG_URL = "https://openrouter.ai/api/v1/models"
# Variants that are not ordinary interactive endpoints. `:batch` trades latency
# for price and cannot serve an interactive agent; `:free` carries its own
# retention terms and rate limits.
EXCLUDED_SUFFIXES = (":batch", ":free", ":extended", ":thinking", ":online")

QualificationState = Literal["CANDIDATE", "QUALIFIED", "QUARANTINED"]

# Which lane executes a model, by catalogue namespace.
NAMESPACE_LANE = {
    "anthropic": "claude_subscription",
    "openai": "codex_api",
}
DEFAULT_LANE = "openrouter"


@dataclass(frozen=True)
class Model:
    """Normalised capability metadata for one model."""

    id: str
    lane: str
    family: str
    harness_model: str
    context_length: int
    max_output_tokens: int
    input_usd_per_mtok: float
    output_usd_per_mtok: float
    supports_tools: bool
    supports_reasoning: bool
    supports_vision: bool
    supports_structured_output: bool
    deprecated: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def normalise(entry: dict[str, Any]) -> Model | None:
    """Turn one catalogue entry into a Model, or None if it is not usable."""
    model_id = str(entry.get("id", ""))
    if not model_id or any(model_id.endswith(s) for s in EXCLUDED_SUFFIXES):
        return None

    params = set(entry.get("supported_parameters") or ())
    architecture = entry.get("architecture") or {}
    pricing = entry.get("pricing") or {}
    top = entry.get("top_provider") or {}
    family = model_id.split("/", 1)[0]

    return Model(
        id=model_id,
        lane=NAMESPACE_LANE.get(family, DEFAULT_LANE),
        family=family,
        # Claude Code and Codex both take the bare slug; only OpenRouter wants
        # the namespaced id.
        harness_model=model_id.split("/", 1)[-1],
        context_length=int(entry.get("context_length") or 0),
        max_output_tokens=int(top.get("max_completion_tokens") or 0),
        input_usd_per_mtok=_num(pricing.get("prompt")) * 1_000_000,
        output_usd_per_mtok=_num(pricing.get("completion")) * 1_000_000,
        supports_tools="tools" in params,
        supports_reasoning="reasoning" in params,
        supports_vision="image" in (architecture.get("input_modalities") or ()),
        supports_structured_output="structured_outputs" in params,
        deprecated=bool(entry.get("expiration_date")),
    )


def fetch(url: str = CATALOG_URL, *, timeout: int = 30) -> list[Model]:
    """Fetch the live catalogue. Raises on network or decode failure."""
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
    models = [normalise(e) for e in payload.get("data", [])]
    return [m for m in models if m is not None]


def discover(url: str = CATALOG_URL, *, timeout: int = 30) -> tuple[list[Model], str]:
    """Fetch the catalogue, returning an empty list and a reason on failure."""
    try:
        return fetch(url, timeout=timeout), "ok"
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        return [], f"catalog discovery failed: {type(exc).__name__}: {exc}"


def merge_qualification(
    models: list[Model], previous: dict[str, Any]
) -> dict[str, Any]:
    """Carry qualification verdicts forward across a catalogue refresh.

    A model keeps whatever verdict it earned. A model the catalogue has not
    shown before enters as CANDIDATE and is not eligible for real work until a
    qualification run promotes it. Newer never means eligible by itself.
    """
    prior_models = previous.get("models", {})
    now = datetime.now(UTC).isoformat(timespec="seconds")
    merged: dict[str, Any] = {}

    for model in models:
        record = dict(prior_models.get(model.id) or {})
        state: QualificationState = record.get("qualification", "CANDIDATE")
        if model.deprecated:
            state = "QUARANTINED"
            record["quarantine_reason"] = "deprecated by provider"
        record.update(model.as_dict())
        record["qualification"] = state
        record["first_seen"] = record.get("first_seen") or now
        record["last_seen"] = now
        merged[model.id] = record

    # Models that vanished from the catalogue are kept with their verdict so a
    # later reappearance does not silently reset to CANDIDATE, but are marked
    # absent so routing skips them.
    for model_id, record in prior_models.items():
        if model_id not in merged:
            gone = dict(record)
            gone["absent"] = True
            merged[model_id] = gone

    return {"generated_at": now, "source": CATALOG_URL, "models": merged}


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"models": {}}
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def save_state(path: Path, state: dict[str, Any]) -> None:
    """LF endings on every platform; see state.write_json for why."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(state, indent=2, sort_keys=True) + "\n"
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(body)


def models_from_state(state: dict[str, Any]) -> list[Model]:
    """Rebuild Model objects from stored state, skipping absent entries."""
    fields = Model.__dataclass_fields__
    models = []
    for record in state.get("models", {}).values():
        if record.get("absent"):
            continue
        models.append(Model(**{k: record[k] for k in fields if k in record}))
    return models


def qualification_of(state: dict[str, Any], model_id: str) -> QualificationState:
    record = state.get("models", {}).get(model_id) or {}
    value: QualificationState = record.get("qualification", "CANDIDATE")
    return value
