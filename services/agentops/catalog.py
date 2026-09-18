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
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

CATALOG_URL = "https://openrouter.ai/api/v1/models"
# Variants that are not ordinary interactive endpoints. `:batch` trades latency
# for price and cannot serve an interactive agent; `:free` carries its own
# retention terms and rate limits.
EXCLUDED_SUFFIXES = (":batch", ":free", ":extended", ":thinking", ":online")
# `openrouter/*` is not a provider family. Those entries are meta-routers and
# aliases -- auto, fusion, pareto-code -- that pick some model at request time.
# Routing to one would mean the capability class, the qualification verdict and
# the privacy contract all describe a model that is not the one which runs.
EXCLUDED_NAMESPACES = ("openrouter",)
# A `~vendor/model-latest` entry is a floating alias: the model behind it
# changes when the vendor ships a new one. A qualification verdict names a
# behaviour that was measured once, so letting an alias carry one means the
# gate can be satisfied by a model that was never tested. Policy already says
# an alias may only be used when a change cannot silently violate
# qualification, and nothing here can detect such a change.
EXCLUDED_PREFIXES = ("~",)

# Aliases that do not name one model. `openrouter/auto` is the obvious one, but
# any `*/auto` or a `:auto` variant has the same problem: the family that
# actually answers is unknown until the request is made, so it could be one the
# owner has confined to a subscription lane.
META_ROUTER_NAMESPACES = ("openrouter",)
META_ROUTER_MARKERS = ("/auto", ":auto", "/router", "/fusion")


def is_meta_router(model_id: str) -> bool:
    """Whether this id routes to some other model chosen at request time."""
    lowered = model_id.lower()
    if lowered.split("/", 1)[0] in META_ROUTER_NAMESPACES:
        return True
    return any(marker in lowered for marker in META_ROUTER_MARKERS)


QualificationState = Literal["CANDIDATE", "QUALIFIED", "QUARANTINED"]

# Which lane executes a model, by catalogue namespace. Derived from policy so
# that changing which lane owns a provider family is a policy edit, not a code
# edit: the OpenAI family moved from the API lane to subscription-backed Codex
# Cloud without touching this module.
DEFAULT_LANE = "openrouter"
FALLBACK_NAMESPACE = "*"


def namespace_lanes(policy: dict[str, Any] | None = None) -> dict[str, str]:
    """Map catalogue namespace -> owning lane, preferring enabled lanes."""
    if policy is None:
        return {"anthropic": "claude_subscription", "openai": "codex_cloud"}
    mapping: dict[str, str] = {}
    for name, lane in sorted(
        policy.get("lanes", {}).items(), key=lambda kv: kv[1].get("priority", 99)
    ):
        namespace = lane.get("catalog_namespace")
        if not namespace or namespace == FALLBACK_NAMESPACE:
            continue
        # First by priority among enabled lanes wins; a disabled lane only
        # claims a namespace nothing enabled has taken.
        if namespace in mapping:
            continue
        if lane.get("enabled", True):
            mapping[namespace] = name
    for name, lane in policy.get("lanes", {}).items():
        namespace = lane.get("catalog_namespace")
        if namespace and namespace != FALLBACK_NAMESPACE and namespace not in mapping:
            mapping[namespace] = name
    return mapping


NAMESPACE_LANE = namespace_lanes()


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


def _harness_model(model_id: str, family: str, lanes: dict[str, str]) -> str:
    """The slug the lane's harness actually accepts.

    Claude Code against the Claude subscription and Codex against the OpenAI
    API both take a bare slug, because the provider is implied. The OpenRouter
    lane routes by namespaced id, so stripping the namespace there would leave
    a model name that identifies nothing.

    Anthropic needs one more step, and until 2026-09-17 not taking it meant no
    local worker could start at all. The catalogue spells a version with a dot
    (`anthropic/claude-haiku-4.5`); Claude Code spells it with a dash. Handed
    the dotted slug the CLI exits immediately with

        [claude-code:unrecognized_model] {"model":"claude-haiku-4.5"}

    which the runtime recorded as an implementation failure, escalated twice
    on, and then dead-ended as BLOCKED_PROVIDER -- twice, on Tasks 15 and 16.
    Probed against the installed CLI: every dotted slug is rejected and every
    dashed one (`claude-haiku-4-5`, `claude-sonnet-4-5`, `claude-opus-4-5`,
    `claude-fable-5-1`) is accepted, as are the already-undotted `claude-*-5`.
    Translating is therefore the whole fix, and an alias like `haiku` is not:
    it would silently run a different tier than the router chose and recorded.
    """
    if family not in lanes:
        return model_id
    return _undot(model_id.split("/", 1)[-1], family)


def _undot(slug: str, family: str) -> str:
    """`claude-haiku-4.5` -> `claude-haiku-4-5`, and nothing else.

    Only a bare Anthropic slug is touched. A namespaced id is left exactly as
    it is: an Anthropic model reached through OpenRouter is addressed by
    OpenRouter's own id, dot included, and dashing that would break a lane
    this function is not being asked about. Independent review raised the
    inverse risk -- that re-deriving ownership here could rewrite a slug as
    though a different lane owned it -- and not re-deriving it is the answer.
    """
    if family == "anthropic" and "/" not in slug:
        return slug.replace(".", "-")
    return slug


def normalise(
    entry: dict[str, Any], lanes: dict[str, str] | None = None
) -> Model | None:
    """Turn one catalogue entry into a Model, or None if it is not usable."""
    lanes = NAMESPACE_LANE if lanes is None else lanes
    model_id = str(entry.get("id", ""))
    if not model_id or any(model_id.endswith(s) for s in EXCLUDED_SUFFIXES):
        return None
    if model_id.split("/", 1)[0] in EXCLUDED_NAMESPACES or is_meta_router(model_id):
        return None
    if model_id.startswith(EXCLUDED_PREFIXES):
        return None

    params = set(entry.get("supported_parameters") or ())
    architecture = entry.get("architecture") or {}
    pricing = entry.get("pricing") or {}
    top = entry.get("top_provider") or {}
    family = model_id.split("/", 1)[0]
    # Which lane may actually run it is decided by the router, which is where
    # the owner's family bans are enforced; the namespace map only says which
    # lane owns the family by default.
    lane = lanes.get(family, DEFAULT_LANE)

    return Model(
        id=model_id,
        lane=lane,
        family=family,
        harness_model=_harness_model(model_id, family, lanes),
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


def priced(model: Model) -> bool:
    """Whether this model has a real, usable price.

    OpenRouter reports a negative sentinel for variable pricing. Sorting
    cheapest-first would then rank those ahead of everything, and a spend
    ceiling cannot bound a cost that is not knowable in advance.
    """
    return model.input_usd_per_mtok >= 0 and model.output_usd_per_mtok >= 0


def fetch(
    url: str = CATALOG_URL, *, timeout: int = 30, lanes: dict[str, str] | None = None
) -> list[Model]:
    """Fetch the live catalogue. Raises on network or decode failure."""
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
    models = [normalise(e, lanes) for e in payload.get("data", [])]
    return [m for m in models if m is not None]


def discover(
    url: str = CATALOG_URL, *, timeout: int = 30, lanes: dict[str, str] | None = None
) -> tuple[list[Model], str]:
    """Fetch the catalogue, returning an empty list and a reason on failure."""
    try:
        return fetch(url, timeout=timeout, lanes=lanes), "ok"
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
        # The provider is listing it again, so clear any earlier absence;
        # otherwise models_from_state would skip it forever.
        record.pop("absent", None)
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
    """Rebuild Model objects from stored state, skipping absent entries.

    The stored harness slug is normalised on the way out. A ledger written
    before the Anthropic translation existed still holds the spelling Claude
    Code rejects, which is exactly how every local worker kept being spawned
    with an unusable model name long after the translation itself was fixed.

    Only the dotted version is corrected; lane ownership is not re-derived.
    Re-deriving it would let this function rewrite a slug as though a
    different lane owned the namespace than the one the router recorded.
    """
    fields = Model.__dataclass_fields__
    models = []
    for record in state.get("models", {}).values():
        if record.get("absent"):
            continue
        model = Model(**{k: record[k] for k in fields if k in record})
        models.append(
            replace(
                model,
                harness_model=_undot(model.harness_model, model.family),
            )
        )
    return models


def qualification_of(state: dict[str, Any], model_id: str) -> QualificationState:
    record = state.get("models", {}).get(model_id) or {}
    value: QualificationState = record.get("qualification", "CANDIDATE")
    return value
