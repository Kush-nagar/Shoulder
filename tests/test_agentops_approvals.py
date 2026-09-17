"""Which discovered models may be handed real Shoulder work.

New models appear in the catalogue weekly, and the cheapest qualifying one is
exactly what a cost-ordered router will reach for. That is the right instinct
for a throwaway evaluation and the wrong one for the next piece of code that
decides who can see a minor's footage. Approval is the deliberate step in
between, and these tests are what stop it being skipped.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from agentops_fixtures import REPO_ROOT, configured_policy, model

from services.agentops import approvals, localstate, routing


def inputs(
    models: list[Any], qualification: dict[str, str] | None = None
) -> routing.RoutingInputs:
    return routing.RoutingInputs(
        policy=configured_policy(),
        models=models,
        qualification=qualification or {m.id: "QUALIFIED" for m in models},
        qualified_lanes=frozenset({"openrouter", "claude_subscription"}),
    )


class ApprovalCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.paths = localstate.ensure(localstate.LocalPaths(Path(self.tmp.name)))
        self.store = approvals.load(self.paths)


class TestTheDefaultIsNotApproval(ApprovalCase):
    def test_a_model_nobody_ruled_on_is_discovered(self) -> None:
        self.assertEqual(
            approvals.state_of(self.store, "deepseek/deepseek-v3"), approvals.DISCOVERED
        )

    def test_a_discovered_model_may_not_take_a_real_task(self) -> None:
        allowed, reason = approvals.may_take(
            self.store,
            "deepseek/deepseek-v3",
            lane="openrouter",
            capability_class="ROUTINE_CODING",
        )
        self.assertFalse(allowed)
        self.assertIn("never approved", reason)

    def test_a_disabled_model_is_refused_outright(self) -> None:
        approvals.set_state(
            self.paths, self.store, "qwen/qwen3-coder", approvals.DISABLED
        )
        allowed, _ = approvals.may_take(
            self.store,
            "qwen/qwen3-coder",
            lane="openrouter",
            capability_class="CHEAP_MECHANICAL",
        )
        self.assertFalse(allowed)

    def test_an_approved_model_may_take_ordinary_work(self) -> None:
        approvals.set_state(
            self.paths, self.store, "deepseek/deepseek-v3", approvals.APPROVED
        )
        allowed, _ = approvals.may_take(
            self.store,
            "deepseek/deepseek-v3",
            lane="openrouter",
            capability_class="ROUTINE_CODING",
        )
        self.assertTrue(allowed)

    def test_native_lane_models_keep_the_behaviour_policy_already_gives_them(
        self,
    ) -> None:
        """Trust for the subscription lane is decided in ops/policy.json, which
        is governance; this layer does not re-litigate it."""
        allowed, _ = approvals.may_take(
            self.store,
            "claude-sonnet-5",
            lane="claude_subscription",
            capability_class="FRONTIER_REASONING",
        )
        self.assertTrue(allowed)


class TestCanaryIsForTryingNotForShipping(ApprovalCase):
    def test_a_canary_model_may_be_evaluated(self) -> None:
        approvals.set_state(self.paths, self.store, "z-ai/glm-4.6", approvals.CANARY)
        allowed, _ = approvals.may_take(
            self.store,
            "z-ai/glm-4.6",
            lane="openrouter",
            capability_class="CHEAP_MECHANICAL",
            purpose="evaluation",
        )
        self.assertTrue(allowed)

    def test_a_canary_model_may_not_take_a_real_task(self) -> None:
        approvals.set_state(self.paths, self.store, "z-ai/glm-4.6", approvals.CANARY)
        allowed, reason = approvals.may_take(
            self.store,
            "z-ai/glm-4.6",
            lane="openrouter",
            capability_class="CHEAP_MECHANICAL",
        )
        self.assertFalse(allowed)
        self.assertIn("evaluation and throwaway work only", reason)


class TestHighRiskNeedsMoreThanApproval(ApprovalCase):
    def test_an_ordinary_approval_is_not_enough_for_a_critical_class(self) -> None:
        approvals.set_state(
            self.paths, self.store, "deepseek/deepseek-v3", approvals.APPROVED
        )
        allowed, reason = approvals.may_take(
            self.store,
            "deepseek/deepseek-v3",
            lane="openrouter",
            capability_class="FRONTIER_REASONING",
        )
        self.assertFalse(allowed)
        self.assertIn("high risk class", reason)

    def test_an_explicit_high_risk_approval_is(self) -> None:
        approvals.set_state(
            self.paths,
            self.store,
            "deepseek/deepseek-v3",
            approvals.APPROVED,
            risk_class="high",
        )
        allowed, _ = approvals.may_take(
            self.store,
            "deepseek/deepseek-v3",
            lane="openrouter",
            capability_class="FRONTIER_REASONING",
        )
        self.assertTrue(allowed)


class TestApprovalReachesTheExistingRouter(ApprovalCase):
    def models(self) -> list[Any]:
        return [
            model("deepseek/deepseek-v3", "openrouter", price_in=0.2, context=200_000),
            model(
                "anthropic/claude-sonnet-5",
                "claude_subscription",
                price_in=3.0,
                context=200_000,
            ),
        ]

    def test_an_unapproved_model_is_not_a_candidate(self) -> None:
        gated = approvals.gate_inputs(
            inputs(self.models()), self.store, capability_class="ROUTINE_CODING"
        )
        self.assertEqual(gated.qualification["deepseek/deepseek-v3"], "UNAPPROVED")

    def test_an_approved_model_stays_a_candidate(self) -> None:
        approvals.set_state(
            self.paths, self.store, "deepseek/deepseek-v3", approvals.APPROVED
        )
        gated = approvals.gate_inputs(
            inputs(self.models()), self.store, capability_class="ROUTINE_CODING"
        )
        self.assertEqual(gated.qualification["deepseek/deepseek-v3"], "QUALIFIED")

    def test_the_native_lane_is_never_gated_by_this_layer(self) -> None:
        gated = approvals.gate_inputs(
            inputs(self.models()), self.store, capability_class="ROUTINE_CODING"
        )
        self.assertEqual(gated.qualification["anthropic/claude-sonnet-5"], "QUALIFIED")

    def test_discovering_a_new_model_changes_no_existing_routing(self) -> None:
        """A model appearing in the catalogue must not silently become the
        cheapest qualifying candidate for tomorrow's task."""
        approvals.set_state(
            self.paths, self.store, "deepseek/deepseek-v3", approvals.APPROVED
        )
        newcomer = model(
            "someone/brand-new-model", "openrouter", price_in=0.01, context=200_000
        )
        gated = approvals.gate_inputs(
            inputs([*self.models(), newcomer]),
            self.store,
            capability_class="ROUTINE_CODING",
        )
        self.assertEqual(gated.qualification["someone/brand-new-model"], "UNAPPROVED")
        self.assertEqual(gated.qualification["deepseek/deepseek-v3"], "QUALIFIED")


class TestCandidateDiscovery(ApprovalCase):
    def test_candidates_come_from_the_catalogue_not_a_hardcoded_winner(self) -> None:
        source = (REPO_ROOT / "services" / "agentops" / "approvals.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("CANDIDATE_FAMILIES", source)
        for family in ("deepseek", "qwen", "moonshotai", "z-ai"):
            self.assertIn(family, source)

    def test_candidates_are_ordered_by_price_and_carry_their_state(self) -> None:
        models = [
            model("deepseek/deepseek-v3", "openrouter", price_in=0.9, context=100_000),
            model("qwen/qwen3-coder", "openrouter", price_in=0.2, context=100_000),
        ]
        rows = approvals.candidates(models, self.store)
        self.assertEqual(rows[0]["id"], "qwen/qwen3-coder")
        self.assertEqual(rows[0]["state"], approvals.DISCOVERED)

    def test_a_native_model_is_not_offered_as_an_openrouter_candidate(self) -> None:
        models = [model("anthropic/claude-opus-5", "claude_subscription", price_in=5.0)]
        self.assertEqual(approvals.candidates(models, self.store), [])


class TestTheStoreIsLocalAndSmall(ApprovalCase):
    def test_it_lives_in_ignored_local_state(self) -> None:
        self.assertIn(".agentops", str(self.paths.approvals))

    def test_a_state_change_is_recorded_as_an_event(self) -> None:
        approvals.set_state(
            self.paths, self.store, "qwen/qwen3-coder", approvals.APPROVED
        )
        kinds = [event["kind"] for event in localstate.events(self.paths)]
        self.assertIn("model_approval", kinds)

    def test_an_unknown_state_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            approvals.set_state(self.paths, self.store, "x/y", "PROBABLY_FINE")


if __name__ == "__main__":
    unittest.main()
