"""Lane, model, and effort selection.

The goal is not the best model everywhere. It is the least expensive current
model and effort setting that is reasonably likely to finish the task
correctly, with escalation as a deliberate, bounded response to failure rather
than a default.

Hard policies bind before cost. They are checked as filters, not as scores, so
no combination of price and availability can route around them:

  * Frontend implementation is written by the OpenAI/Codex lane only.
  * A model that has not passed qualification never takes real work.
  * A provider that cannot meet the privacy contract is ineligible at any price.
  * When nothing legitimate is available the result is BLOCKED_PROVIDER, never
    a quiet downgrade.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from . import catalog
from .catalog import Model
from .classify import Classification

Effort = Literal["low", "medium", "high", "xhigh"]
ProviderHealth = Literal[
    "AVAILABLE",
    "DEGRADED",
    "COOLDOWN",
    "BUDGET_EXHAUSTED",
    "AUTH_FAILED",
    "UNAVAILABLE",
    "DISABLED",
]
# DEGRADED means "was failing, has not yet proven it recovered". It is not
# usable: treating it as usable meant a harness failure recorded DEGRADED and
# the very next routing decision picked the same lane again, so the recorded
# fallback chain was never taken. A lane returns to AVAILABLE only by a real
# success.
USABLE_HEALTH = ("AVAILABLE",)


class RoutingBlocked(Exception):
    """No authorised lane can legitimately take this work."""

    def __init__(self, reason: str, rejections: list[str]) -> None:
        super().__init__(reason)
        self.reason = reason
        self.rejections = rejections


@dataclass(frozen=True)
class Assignment:
    lane: str
    model: str
    harness: str
    harness_model: str
    effort: Effort
    capability_class: str
    reason: str
    mechanism: str = "workflow-dispatch"
    # False when the lane cannot be told which model to use, so the recorded
    # tier is a decision rather than an applied setting.
    model_enforced: bool = True
    # The catalogue entry used to prove the capability class is satisfiable.
    # On a non-enforcing lane it is evidence for the decision, not the model
    # that will run.
    representative_model: str = ""
    fallbacks: tuple[tuple[str, str], ...] = ()
    rejections: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "lane": self.lane,
            "model": self.model,
            "harness": self.harness,
            "harness_model": self.harness_model,
            "effort": self.effort,
            "capability_class": self.capability_class,
            "mechanism": self.mechanism,
            "model_enforced": self.model_enforced,
            "representative_model": self.representative_model,
            "reason": self.reason,
            "fallbacks": [list(f) for f in self.fallbacks],
            "rejections": list(self.rejections),
        }


@dataclass
class RoutingInputs:
    policy: dict[str, Any]
    models: list[Model]
    qualification: dict[str, str]
    provider_health: dict[str, str] = field(default_factory=dict)
    budget_blocked: frozenset[str] = frozenset()
    # Lanes proven to work end to end. Only consulted for lanes that cannot be
    # told which model to use, where per-model qualification says nothing.
    qualified_lanes: frozenset[str] = frozenset()


def capability_class(policy: dict[str, Any], c: Classification) -> str:
    """The tier this task earns.

    A reviewer uses the same class as the writer rather than one of its own:
    risk already decided the class, so a separate review tier would either
    under-resource a critical review or waste capability on a trivial one.
    """
    table = policy["classification_to_class"]
    mapping = table.get(c.category, table["backend"])
    name: str = mapping[c.complexity]
    # A task that genuinely needs to be looked at in a browser needs a model
    # that can see. Complexity alone does not imply that.
    if c.visual_required and c.category in ("frontend", "mixed"):
        name = "VISUAL_FRONTEND"
    return name


def effort_for(policy: dict[str, Any], class_name: str, escalations: int = 0) -> Effort:
    ladder: list[Effort] = list(policy["effort_ladder"])
    base: Effort = policy["capability_classes"][class_name]["effort"]
    index = min(ladder.index(base) + max(escalations, 0), len(ladder) - 1)
    return ladder[index]


def _lane_may_write(lane: dict[str, Any], category: str, purpose: str) -> bool:
    if purpose == "review":
        return bool(lane.get("may_review"))
    if category == "frontend":
        return bool(lane.get("may_write_frontend"))
    if category == "mixed":
        # A mixed task that is not split must be taken by a lane allowed to
        # write both halves, rather than letting a backend-only lane touch UI.
        return bool(lane.get("may_write_frontend")) and bool(
            lane.get("may_write_backend")
        )
    return bool(lane.get("may_write_backend"))


def eligible_models(
    inputs: RoutingInputs, class_name: str, lane_name: str
) -> list[Model]:
    spec = inputs.policy["capability_classes"][class_name]
    required = inputs.policy["qualification"]["required_states"]
    lane = inputs.policy["lanes"].get(lane_name, {})
    # A lane that cannot be told which model to use runs whatever the account
    # has configured, so qualifying a particular model there would prove
    # nothing about what actually executes. Such a lane is gated on the lane
    # itself having been proven end to end instead; see qualified_lanes.
    enforces_model = bool(lane.get("model_enforced", True))
    # Owner policy, enforced here rather than only where the catalogue assigns
    # lanes: this is the one point every selection passes through, so a stale
    # state file, a hand edit, or a future catalogue change cannot put a banned
    # family back on a lane. Matching is on the model id's own namespace, not on
    # a lane's declared provider, because the id is what the harness sends.
    banned = tuple(lane.get("banned_namespaces", ()))
    reject_meta = bool(lane.get("reject_meta_routers"))

    # The catalogue assigns each family to exactly one owning lane, which was
    # fine while one lane per family could run it. Two lanes now reach the same
    # OpenAI subscription -- the local CLI and the cloud mention -- and only one
    # of them can own the namespace. So a lane also serves a family it declares
    # as its own namespace, which is what lets both Codex lanes see the same
    # models. No other lane's set changes: every other lane already owns the
    # namespace it declares, and the OpenRouter lane declares `*`, which is not
    # a family any model has.
    namespace = lane.get("catalog_namespace")
    out = []
    for model in inputs.models:
        if model.deprecated:
            continue
        if model.lane != lane_name and model.family != namespace:
            continue
        if model.family in banned:
            continue
        if reject_meta and catalog.is_meta_router(model.id):
            continue
        if not catalog.priced(model):
            # A price that is not knowable cannot be bounded by a ceiling.
            continue
        if (
            enforces_model
            and inputs.qualification.get(model.id, "CANDIDATE") not in required
        ):
            continue
        if model.context_length < spec["min_context"]:
            continue
        if spec["needs_tools"] and not model.supports_tools:
            continue
        if spec["needs_vision"] and not model.supports_vision:
            continue
        if spec["needs_reasoning"] and not model.supports_reasoning:
            continue
        if model.input_usd_per_mtok > spec["max_input_usd_per_mtok"]:
            continue
        out.append(model)
    # Within a class, cheapest first: a subscription allowance is finite too,
    # and a stronger model drains a five-hour window faster, so "there is no
    # cost to optimise" is false even where no invoice arrives.
    #
    # But cheapest-first is only right once the bar is cleared, and for the
    # upper classes the class spec cannot state the bar: it can require context,
    # tools, vision and reasoning, none of which separate a cheap model from a
    # frontier one. Left to cheapest-first, every class above ROUTINE resolves
    # to the same cheap tier and the ladder collapses into one rung. So those
    # classes ask for the strongest model under their ceiling instead, price
    # being the only capability proxy here that does not hard-code model names.
    direction = -1.0 if spec.get("prefer") == "strongest" else 1.0
    return sorted(
        out,
        key=lambda m: (
            direction * m.input_usd_per_mtok,
            direction * m.output_usd_per_mtok,
            m.id,
        ),
    )


def privacy_violation(policy: dict[str, Any], lane: dict[str, Any]) -> str | None:
    """Why this lane fails the privacy contract, or None if it satisfies it.

    Shoulder handles minors' data, so the contract is a filter rather than a
    preference: a lane that does not declare it is ineligible at any price. A
    lane missing the declaration fails closed, which is why the default is
    False rather than "assume fine".
    """
    required = policy["privacy"]
    if required.get("require_zero_data_retention") and not lane.get(
        "zero_data_retention", False
    ):
        return "does not declare zero data retention"
    if required.get("deny_data_collection") and lane.get("data_collection") != "deny":
        return "does not deny provider data collection"
    if lane.get("requires_privacy_confirmation") and not lane.get("privacy_confirmed"):
        # The setting lives on the provider account and this repository cannot
        # read it, so the only honest state is unconfirmed until the owner says
        # otherwise. The harness does not send per-request privacy fields, so
        # nothing here can compensate.
        return (
            "account-level privacy has not been confirmed; "
            "run `cli confirm-privacy --lane <lane>`"
        )
    return None


def _ordered_lanes(
    policy: dict[str, Any], class_name: str = ""
) -> list[tuple[str, dict[str, Any]]]:
    """Lanes in the order this class wants them tried.

    Priority alone could not express the routing table this system actually
    runs. It is a single global order, so it can say "Codex before Claude" or
    the reverse, but not "Codex writes the security migration and Claude writes
    the ordinary endpoint" -- and that distinction is the whole point of having
    both. The capability class is where difficulty has already been decided, so
    it is where the preference belongs.

    This reorders; it never admits anything. Every filter in `select` still
    runs, so a preferred lane that is unhealthy, over budget, unqualified or
    forbidden to write this category is still rejected and the next lane in the
    order takes the work. A class that states no preference keeps the global
    priority order exactly as before.
    """
    preferred: list[str] = []
    if class_name:
        spec = policy.get("capability_classes", {}).get(class_name, {})
        preferred = list(spec.get("prefer_lanes", ()))

    def rank(item: tuple[str, dict[str, Any]]) -> tuple[int, int]:
        name, lane = item
        first = preferred.index(name) if name in preferred else len(preferred)
        return (first, lane["priority"])

    return sorted(policy["lanes"].items(), key=rank)


def select(
    inputs: RoutingInputs,
    classification: Classification,
    *,
    purpose: str = "implement",
    effort_escalations: int = 0,
    exclude_lanes: frozenset[str] = frozenset(),
    exclude_family: str | None = None,
) -> Assignment:
    """Choose a lane, model, and effort, or raise RoutingBlocked."""
    class_name = capability_class(inputs.policy, classification)
    effort = effort_for(inputs.policy, class_name, effort_escalations)
    rejections: list[str] = []
    chain: list[tuple[str, str]] = []
    chosen: tuple[str, dict[str, Any], Model] | None = None

    for lane_name, lane in _ordered_lanes(inputs.policy, class_name):
        if lane_name in exclude_lanes:
            rejections.append(f"{lane_name}: excluded by caller")
            continue
        if not lane.get("enabled", True):
            rejections.append(f"{lane_name}: lane is disabled in policy")
            continue
        if not _lane_may_write(lane, classification.category, purpose):
            rejections.append(
                f"{lane_name}: policy forbids {purpose} of "
                f"{classification.category} work"
            )
            continue
        if exclude_family and lane["provider"] == exclude_family:
            rejections.append(f"{lane_name}: same provider family as the writer")
            continue
        privacy_failure = privacy_violation(inputs.policy, lane)
        if privacy_failure:
            rejections.append(f"{lane_name}: {privacy_failure}")
            continue
        if (
            not lane.get("model_enforced", True)
            and lane_name not in inputs.qualified_lanes
        ):
            rejections.append(
                f"{lane_name}: lane has not passed an end-to-end qualification run"
            )
            continue
        health = inputs.provider_health.get(lane_name, "AVAILABLE")
        if health not in USABLE_HEALTH:
            rejections.append(f"{lane_name}: provider health {health}")
            continue
        if lane["billing"] == "api" and lane_name in inputs.budget_blocked:
            rejections.append(f"{lane_name}: budget ceiling reached")
            continue

        candidates = eligible_models(inputs, class_name, lane_name)
        if not candidates:
            rejections.append(f"{lane_name}: no qualified model meets {class_name}")
            continue

        if chosen is None:
            chosen = (lane_name, lane, candidates[0])
        else:
            chain.append((lane_name, candidates[0].id))

    if chosen is None:
        raise RoutingBlocked(
            f"BLOCKED_PROVIDER: no authorised lane can {purpose} a "
            f"{classification.category}/{classification.complexity} task",
            rejections,
        )

    lane_name, lane, model = chosen
    enforced = bool(lane.get("model_enforced", True))
    # Reporting a specific slug for a lane that cannot be told which model to
    # use is worse than reporting none: a log saying "gpt-5-nano" for a
    # STRONG_CODING task reads as a decision that was never made and never
    # applied. The class is the real decision; the model is whatever the
    # account has configured.
    if enforced:
        harness_model = model.harness_model
    else:
        # A lane whose model does not come from the catalogue may still name the
        # slug its harness is handed. codex_local does: `codex exec -m` takes
        # one, and the routed effort reaches `-c model_reasoning_effort`, so
        # reporting "account-configured" would understate what was applied.
        # codex_cloud names none, because a mention cannot carry one, and there
        # the honest answer is still that the account decides.
        harness_model = str(lane.get("harness_model") or "") or "account-configured"
    preference = inputs.policy["capability_classes"][class_name].get(
        "prefer", "cheapest"
    )
    reason = (
        f"{classification.category}/{classification.complexity} -> {class_name}; "
        f"{preference} qualified model in lane {lane_name} "
        f"at ${model.input_usd_per_mtok:.3f}/Mtok in"
    )
    if not enforced and harness_model == "account-configured":
        # Codex Cloud is reached by mentioning @codex on a pull request, and a
        # mention carries no model or effort. The tier is still chosen and
        # recorded so the decision is auditable, but saying it was applied
        # would be false.
        reason += "; tier is advisory, the account's configured Codex model runs"
    elif not enforced:
        reason += (
            f"; model is not catalogue-chosen, the lane runs {harness_model} "
            f"at {effort} effort"
        )
    return Assignment(
        lane=lane_name,
        model=model.id,
        harness=lane["harness"],
        harness_model=harness_model,
        representative_model=model.id,
        effort=effort,
        capability_class=class_name,
        mechanism=str(lane.get("mechanism", "workflow-dispatch")),
        model_enforced=enforced,
        reason=reason,
        fallbacks=tuple(chain),
        rejections=tuple(rejections),
    )


def select_reviewer(
    inputs: RoutingInputs, classification: Classification, writer: Assignment
) -> Assignment:
    """Pick an independent reviewer from a different provider family."""
    writer_family = inputs.policy["lanes"][writer.lane]["provider"]
    return select(
        inputs,
        classification,
        purpose="review",
        exclude_family=writer_family,
    )
