"""Which discovered models may be given real Shoulder work.

The catalogue discovers everything OpenRouter currently serves, and new models
appear there weekly. Existing qualification already proves a model follows the
instruction hierarchy on synthetic material, which is necessary and is not the
same as having earned a task in this repository. A model that appeared this
morning should be able to be tried; it should not silently inherit the next
piece of coach-authored judgment code because it was cheapest that hour.

So approval is a separate, local, deliberately boring state per model:

    DISCOVERED  in the catalogue, never approved for anything here
    CANARY      may run evaluations and throwaway work, never a real task
    APPROVED    may take real tasks
    DISABLED    refused outright

It applies to the OpenRouter lane. Anthropic models on the subscription lane
keep the behaviour existing policy already gives them -- that trust decision is
made in `ops/policy.json`, which is governance, and is not re-litigated here.

The store is small and local, because it records what this workstation has
decided to trust, not what the repository asserts.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from services.agentops import localstate, routing

DISCOVERED = "DISCOVERED"
CANARY = "CANARY"
APPROVED = "APPROVED"
DISABLED = "DISABLED"

STATES = (DISCOVERED, CANARY, APPROVED, DISABLED)

# Work that can lose data, expose a minor's footage, or wire an authorisation
# path. A model needs more than an ordinary approval to be handed one.
HIGH_RISK_CLASSES = ("FRONTIER_REASONING", "LONG_HORIZON_AGENT")

# The lane whose models this governs. The subscription lane is governed by
# policy and qualification, which already exist.
GOVERNED_LANES = ("openrouter",)

# Families worth trying first when the operator asks what to evaluate. These
# are candidates, not a ranking and not a permanent list: the catalogue is the
# authority on what exists, and an approval is the only thing that grants work.
CANDIDATE_FAMILIES = (
    "deepseek",
    "z-ai",
    "moonshotai",
    "qwen",
    "mistralai",
    "x-ai",
)


def load(paths: localstate.LocalPaths) -> dict[str, Any]:
    return localstate.read(
        paths.approvals,
        {
            "$comment": (
                "Local model approval. DISCOVERED and DISABLED models never "
                "take work; CANARY may run evaluations and throwaway tasks; "
                "APPROVED may take real tasks. High-risk classes additionally "
                "require risk_class 'high'."
            ),
            "models": {},
        },
    )


def save(paths: localstate.LocalPaths, store: dict[str, Any]) -> None:
    localstate.write(paths.approvals, store)


def record(store: dict[str, Any], model_id: str) -> dict[str, Any]:
    entry = (store.get("models") or {}).get(model_id)
    return dict(entry) if isinstance(entry, dict) else {}


def state_of(store: dict[str, Any], model_id: str) -> str:
    """A model nobody has ruled on is DISCOVERED, never approved by default."""
    state = str(record(store, model_id).get("state") or DISCOVERED)
    return state if state in STATES else DISCOVERED


def risk_class_of(store: dict[str, Any], model_id: str) -> str:
    return str(record(store, model_id).get("risk_class") or "standard")


def set_state(
    paths: localstate.LocalPaths,
    store: dict[str, Any],
    model_id: str,
    state: str,
    *,
    risk_class: str | None = None,
    note: str = "",
) -> dict[str, Any]:
    if state not in STATES:
        raise ValueError(f"{state} is not one of {', '.join(STATES)}")
    models = store.setdefault("models", {})
    entry = dict(models.get(model_id) or {})
    entry.update(
        {
            "state": state,
            "changed_at": localstate.now(),
            "note": note or entry.get("note", ""),
        }
    )
    if risk_class:
        entry["risk_class"] = risk_class
    models[model_id] = entry
    save(paths, store)
    localstate.append_event(
        paths, "model_approval", model=model_id, state=state, risk_class=risk_class
    )
    return entry


def may_take(
    store: dict[str, Any],
    model_id: str,
    *,
    lane: str,
    capability_class: str,
    purpose: str = "task",
) -> tuple[bool, str]:
    """Whether this model may be handed this piece of work.

    `purpose` separates real work from an evaluation: a CANARY model exists
    precisely so it can be tried on something disposable before anything else
    is decided about it.
    """
    if lane not in GOVERNED_LANES:
        return True, "lane is governed by policy qualification, not local approval"

    state = state_of(store, model_id)
    if state == DISABLED:
        return False, f"{model_id} is DISABLED locally"
    if state == DISCOVERED:
        return False, (
            f"{model_id} is DISCOVERED but never approved; "
            "approve it locally before it takes work"
        )
    if state == CANARY and purpose != "evaluation":
        return False, f"{model_id} is CANARY: evaluation and throwaway work only"
    if (
        capability_class in HIGH_RISK_CLASSES
        and risk_class_of(store, model_id) != "high"
        and purpose != "evaluation"
    ):
        return False, (
            f"{model_id} is approved for standard work only; "
            f"{capability_class} needs an explicit high risk class"
        )
    return True, f"{model_id} is {state}"


def gate_inputs(
    inputs: routing.RoutingInputs,
    store: dict[str, Any],
    *,
    capability_class: str,
    purpose: str = "task",
) -> routing.RoutingInputs:
    """Hand the existing router an approval-aware view of the catalogue.

    Approval is expressed as qualification rather than as a second router: a
    model that may not take this work is simply not a qualified candidate for
    it, and every existing rejection message, fallback chain and escalation
    path keeps working unchanged.
    """
    qualification = dict(inputs.qualification)
    for model in inputs.models:
        if model.lane not in GOVERNED_LANES:
            continue
        allowed, _ = may_take(
            store,
            model.id,
            lane=model.lane,
            capability_class=capability_class,
            purpose=purpose,
        )
        if not allowed:
            qualification[model.id] = "UNAPPROVED"
    return dataclasses.replace(inputs, qualification=qualification)


def summary(store: dict[str, Any]) -> dict[str, list[str]]:
    """Models by state, for the dashboard and `models` command."""
    out: dict[str, list[str]] = {state: [] for state in STATES}
    for model_id, entry in sorted((store.get("models") or {}).items()):
        state = str(entry.get("state") or DISCOVERED)
        out.setdefault(state, []).append(model_id)
    return out


def candidates(
    models: list[Any], store: dict[str, Any], limit: int = 12
) -> list[dict[str, Any]]:
    """Catalogue entries worth evaluating next, cheapest first.

    Nothing here approves anything. It answers "what should I try?", which is
    the question that otherwise gets answered by whichever name someone
    remembered from a blog post.
    """
    rows = []
    for model in models:
        if model.lane not in GOVERNED_LANES:
            continue
        if not model.supports_tools or model.deprecated:
            continue
        if model.family not in CANDIDATE_FAMILIES:
            continue
        rows.append(
            {
                "id": model.id,
                "family": model.family,
                "context": model.context_length,
                "input_usd_per_mtok": round(model.input_usd_per_mtok, 4),
                "output_usd_per_mtok": round(model.output_usd_per_mtok, 4),
                "tools": model.supports_tools,
                "reasoning": model.supports_reasoning,
                "state": state_of(store, model.id),
            }
        )
    rows.sort(key=lambda row: row["input_usd_per_mtok"])
    return rows[:limit]
