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
USABLE_HEALTH = ("AVAILABLE", "DEGRADED")


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
    out = []
    for model in inputs.models:
        if model.lane != lane_name or model.deprecated:
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
    # Cheapest first: the least expensive model that clears every requirement.
    return sorted(
        out, key=lambda m: (m.input_usd_per_mtok, m.output_usd_per_mtok, m.id)
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
    return None


def _ordered_lanes(policy: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return sorted(policy["lanes"].items(), key=lambda kv: kv[1]["priority"])


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

    for lane_name, lane in _ordered_lanes(inputs.policy):
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
    reason = (
        f"{classification.category}/{classification.complexity} -> {class_name}; "
        f"cheapest qualified model in lane {lane_name} "
        f"at ${model.input_usd_per_mtok:.3f}/Mtok in"
    )
    if not enforced:
        # Codex Cloud is reached by mentioning @codex on a pull request, and a
        # mention carries no model or effort. The tier is still chosen and
        # recorded so the decision is auditable, but saying it was applied
        # would be false.
        reason += "; tier is advisory, the account's configured Codex model runs"
    return Assignment(
        lane=lane_name,
        model=model.id,
        harness=lane["harness"],
        harness_model=model.harness_model,
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
