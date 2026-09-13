"""Cost-aware routing, hard policy enforcement, failover, and qualification."""

from __future__ import annotations

import unittest
from typing import Any

from agentops_fixtures import model, model_pool, policy, qualification, real_backlog

from services.agentops import (
    backlog,
    catalog,
    classify,
    notify,
    qualify,
    routing,
    state,
)


def task(
    task_id: int = 90,
    *,
    title: str = "A task",
    body: str = "Do a thing.",
    test: str = "it passes.",
    read: tuple[str, ...] = (),
    prerequisites: tuple[int, ...] = (),
) -> backlog.Task:
    return backlog.Task(
        id=task_id,
        title=title,
        phase="Phase C — The manual product",
        prerequisites=prerequisites,
        gated=False,
        read=read,
        test=test,
        done="done.",
        body=body,
    )


def inputs(**overrides: object) -> routing.RoutingInputs:
    models = model_pool()
    base: dict[str, Any] = {
        "policy": policy(),
        "models": models,
        "qualification": qualification(models),
        "provider_health": {},
        "budget_blocked": frozenset(),
    }
    base.update(overrides)
    return routing.RoutingInputs(**base)


def classification(
    category: str, complexity: str, **flags: object
) -> classify.Classification:
    defaults: dict[str, Any] = dict(
        task_id=90,
        category=category,
        complexity=complexity,
        security_risk=False,
        destructive_risk=False,
        migration_risk=False,
        visual_required=False,
        browser_required=False,
        context7_expected=False,
        prerequisite_count=0,
        test_clause_count=1,
        read_doc_count=0,
        reasons=("synthetic",),
    )
    defaults.update(flags)
    return classify.Classification(**defaults)


class TestCostAwareSelection(unittest.TestCase):
    """10-13. Cheap work gets cheap models; hard work earns capability."""

    def test_trivial_backend_work_takes_a_cheap_model(self) -> None:
        chosen = routing.select(inputs(), classification("backend", "TRIVIAL"))
        self.assertEqual(chosen.capability_class, "CHEAP_MECHANICAL")
        self.assertEqual(chosen.effort, "low")
        self.assertLessEqual(
            next(m.input_usd_per_mtok for m in model_pool() if m.id == chosen.model),
            1.5,
        )

    def test_routine_backend_work_uses_a_balanced_model(self) -> None:
        chosen = routing.select(inputs(), classification("backend", "ROUTINE"))
        self.assertEqual(chosen.capability_class, "ROUTINE_CODING")
        self.assertEqual(chosen.effort, "medium")

    def test_complex_backend_work_uses_a_strong_model(self) -> None:
        chosen = routing.select(inputs(), classification("backend", "COMPLEX"))
        self.assertEqual(chosen.capability_class, "STRONG_CODING")
        self.assertEqual(chosen.effort, "high")

    def test_critical_security_work_uses_frontier_capability(self) -> None:
        chosen = routing.select(
            inputs(), classification("backend", "CRITICAL", security_risk=True)
        )
        self.assertEqual(chosen.capability_class, "FRONTIER_REASONING")
        self.assertEqual(chosen.effort, "high")

    def test_selection_picks_the_cheapest_model_that_clears_the_bar(self) -> None:
        candidates = routing.eligible_models(
            inputs(), "ROUTINE_CODING", "claude_subscription"
        )
        prices = [m.input_usd_per_mtok for m in candidates]
        self.assertEqual(prices, sorted(prices))
        chosen = routing.select(inputs(), classification("backend", "ROUTINE"))
        self.assertEqual(chosen.model, candidates[0].id)


class TestFrontendHardPolicy(unittest.TestCase):
    """14-17. The frontend writer restriction cannot be routed around."""

    def test_claude_never_writes_frontend_code(self) -> None:
        chosen = routing.select(inputs(), classification("frontend", "ROUTINE"))
        self.assertEqual(chosen.lane, "codex_api")
        self.assertNotEqual(chosen.lane, "claude_subscription")

    def test_deepseek_never_writes_frontend_code(self) -> None:
        for complexity in ("TRIVIAL", "ROUTINE", "COMPLEX", "CRITICAL", "EXTREME"):
            chosen = routing.select(inputs(), classification("frontend", complexity))
            self.assertEqual(chosen.lane, "codex_api", complexity)
            self.assertFalse(chosen.model.startswith("deepseek/"), complexity)

    def test_frontend_blocks_rather_than_falling_back_to_claude(self) -> None:
        """The lane being down must not hand UI work to a forbidden writer."""
        with self.assertRaises(routing.RoutingBlocked) as raised:
            routing.select(
                inputs(provider_health={"codex_api": "UNAVAILABLE"}),
                classification("frontend", "ROUTINE"),
            )
        self.assertIn("BLOCKED_PROVIDER", raised.exception.reason)

    def test_ordinary_frontend_work_avoids_frontier_models(self) -> None:
        chosen = routing.select(inputs(), classification("frontend", "ROUTINE"))
        price = next(m.input_usd_per_mtok for m in model_pool() if m.id == chosen.model)
        self.assertLess(price, 1.0)

    def test_hard_visual_frontend_can_escalate_to_a_vision_model(self) -> None:
        chosen = routing.select(
            inputs(),
            classification("frontend", "CRITICAL", visual_required=True),
        )
        self.assertEqual(chosen.capability_class, "VISUAL_FRONTEND")
        self.assertEqual(chosen.lane, "codex_api")
        selected = next(m for m in model_pool() if m.id == chosen.model)
        self.assertTrue(selected.supports_vision)

    def test_mixed_task_requires_a_lane_that_may_write_both_halves(self) -> None:
        chosen = routing.select(inputs(), classification("mixed", "COMPLEX"))
        lane = policy()["lanes"][chosen.lane]
        self.assertTrue(lane["may_write_frontend"] and lane["may_write_backend"])


class TestEffortLadder(unittest.TestCase):
    """18-20. Lowest reasonable effort first; max effort is an escalation."""

    def test_lowest_effort_is_chosen_initially(self) -> None:
        self.assertEqual(routing.effort_for(policy(), "CHEAP_MECHANICAL", 0), "low")

    def test_max_effort_is_never_the_initial_default(self) -> None:
        for name in policy()["capability_classes"]:
            self.assertNotEqual(routing.effort_for(policy(), name, 0), "xhigh", name)

    def test_effort_escalates_one_step_at_a_time(self) -> None:
        self.assertEqual(routing.effort_for(policy(), "ROUTINE_CODING", 0), "medium")
        self.assertEqual(routing.effort_for(policy(), "ROUTINE_CODING", 1), "high")
        self.assertEqual(routing.effort_for(policy(), "ROUTINE_CODING", 2), "xhigh")

    def test_effort_never_exceeds_the_ladder(self) -> None:
        self.assertEqual(routing.effort_for(policy(), "ROUTINE_CODING", 99), "xhigh")

    def test_model_escalates_when_failures_raise_complexity(self) -> None:
        """21. Repeated failure buys a stronger class, not just more effort."""
        source = task(body="Adjust a queue helper.", test="unit test passes.")
        first = routing.select(inputs(), classify.classify(source))
        escalated = routing.select(
            inputs(), classify.classify(source, prior_failures=2)
        )
        self.assertNotEqual(first.capability_class, escalated.capability_class)


class TestProviderFailover(unittest.TestCase):
    """22-30. Provider health, budgets, and failing closed."""

    def test_claude_unavailable_falls_back_to_another_lane(self) -> None:
        chosen = routing.select(
            inputs(provider_health={"claude_subscription": "UNAVAILABLE"}),
            classification("backend", "ROUTINE"),
        )
        self.assertNotEqual(chosen.lane, "claude_subscription")

    def test_both_subscription_lanes_down_reaches_openrouter(self) -> None:
        chosen = routing.select(
            inputs(
                provider_health={
                    "claude_subscription": "COOLDOWN",
                    "codex_api": "UNAVAILABLE",
                }
            ),
            classification("backend", "ROUTINE"),
        )
        self.assertEqual(chosen.lane, "openrouter")

    def test_budget_exhaustion_removes_an_api_lane(self) -> None:
        chosen = routing.select(
            inputs(
                provider_health={"claude_subscription": "UNAVAILABLE"},
                budget_blocked=frozenset({"openrouter"}),
            ),
            classification("backend", "ROUTINE"),
        )
        self.assertEqual(chosen.lane, "codex_api")

    def test_budget_never_blocks_the_subscription_lane(self) -> None:
        chosen = routing.select(
            inputs(budget_blocked=frozenset({"openrouter", "codex_api"})),
            classification("backend", "ROUTINE"),
        )
        self.assertEqual(chosen.lane, "claude_subscription")

    def test_every_lane_unavailable_blocks_safely(self) -> None:
        with self.assertRaises(routing.RoutingBlocked) as raised:
            routing.select(
                inputs(
                    provider_health={
                        "claude_subscription": "UNAVAILABLE",
                        "codex_api": "AUTH_FAILED",
                        "openrouter": "BUDGET_EXHAUSTED",
                    }
                ),
                classification("backend", "ROUTINE"),
            )
        self.assertIn("BLOCKED_PROVIDER", raised.exception.reason)
        self.assertEqual(len(raised.exception.rejections), 3)

    def test_a_fallback_chain_is_recorded(self) -> None:
        chosen = routing.select(inputs(), classification("backend", "ROUTINE"))
        self.assertTrue(chosen.fallbacks)
        self.assertNotIn(chosen.lane, [lane for lane, _ in chosen.fallbacks])

    def test_degraded_lane_is_still_usable(self) -> None:
        chosen = routing.select(
            inputs(provider_health={"claude_subscription": "DEGRADED"}),
            classification("backend", "ROUTINE"),
        )
        self.assertEqual(chosen.lane, "claude_subscription")


class TestProviderHealthState(unittest.TestCase):
    """23-24. Cooldown and recovery after a legitimate reset."""

    def test_cooldown_expires_to_degraded_not_available(self) -> None:
        providers = state.mark_provider(
            {"lanes": {}},
            "openrouter",
            "COOLDOWN",
            reason="rate limited",
            reset_at="2000-01-01T00:00:00+00:00",
        )
        self.assertEqual(state.provider_health(providers)["openrouter"], "DEGRADED")

    def test_cooldown_before_reset_stays_in_cooldown(self) -> None:
        providers = state.mark_provider(
            {"lanes": {}},
            "openrouter",
            "COOLDOWN",
            reason="rate limited",
            reset_at="2999-01-01T00:00:00+00:00",
        )
        self.assertEqual(state.provider_health(providers)["openrouter"], "COOLDOWN")

    def test_returning_to_available_clears_the_reset_and_failures(self) -> None:
        providers = state.mark_provider({"lanes": {}}, "openrouter", "COOLDOWN")
        providers = state.mark_provider(providers, "openrouter", "AVAILABLE")
        record = providers["lanes"]["openrouter"]
        self.assertNotIn("reset_at", record)
        self.assertEqual(record["failure_count"], 0)

    def test_budget_ceiling_blocks_the_right_lane(self) -> None:
        """53. Spend ceilings are enforced, per lane and per period."""
        settings = policy()
        budget = state.record_spend(
            {}, "openrouter", settings["budget"]["openrouter_daily_usd"]
        )
        self.assertIn("openrouter", state.budget_blocked(settings, budget))
        self.assertNotIn("codex_api", state.budget_blocked(settings, budget))

    def test_spend_below_the_ceiling_does_not_block(self) -> None:
        settings = policy()
        budget = state.record_spend({}, "openrouter", 0.01)
        self.assertEqual(state.budget_blocked(settings, budget), frozenset())


class TestQualification(unittest.TestCase):
    """31-40. Discovery, candidate gating, privacy, and promotion timing."""

    def test_catalog_entries_normalise_to_capabilities(self) -> None:
        entry = {
            "id": "deepseek/deepseek-v4-flash",
            "context_length": 1_048_576,
            "architecture": {"input_modalities": ["text"]},
            "pricing": {"prompt": "0.00000007", "completion": "0.00000013"},
            "top_provider": {"max_completion_tokens": 32768},
            "supported_parameters": ["tools", "reasoning", "structured_outputs"],
        }
        normalised = catalog.normalise(entry)
        assert normalised is not None
        self.assertEqual(normalised.lane, "openrouter")
        self.assertEqual(normalised.harness_model, "deepseek-v4-flash")
        self.assertTrue(normalised.supports_tools)
        self.assertFalse(normalised.supports_vision)
        self.assertAlmostEqual(normalised.input_usd_per_mtok, 0.07)

    def test_namespaces_map_to_their_owning_lane(self) -> None:
        anthropic = catalog.normalise({"id": "anthropic/claude-sonnet-5"})
        openai = catalog.normalise({"id": "openai/gpt-5-mini"})
        assert anthropic is not None and openai is not None
        self.assertEqual(anthropic.lane, "claude_subscription")
        self.assertEqual(openai.lane, "codex_api")

    def test_batch_and_free_variants_are_not_discovered(self) -> None:
        for model_id in ("openai/gpt-5-mini:batch", "deepseek/deepseek-v4-flash:free"):
            self.assertIsNone(catalog.normalise({"id": model_id}))

    def test_new_model_enters_as_candidate(self) -> None:
        merged = catalog.merge_qualification(
            [model("vendor/brand-new", "openrouter")], {"models": {}}
        )
        self.assertEqual(
            merged["models"]["vendor/brand-new"]["qualification"], "CANDIDATE"
        )

    def test_candidate_model_never_takes_real_work(self) -> None:
        models = model_pool()
        marks = qualification(models)
        marks["deepseek/deepseek-v4-flash"] = "CANDIDATE"
        eligible = routing.eligible_models(
            inputs(models=models, qualification=marks), "CHEAP_MECHANICAL", "openrouter"
        )
        self.assertNotIn("deepseek/deepseek-v4-flash", [m.id for m in eligible])

    def test_quarantined_model_never_takes_real_work(self) -> None:
        models = model_pool()
        marks = qualification(models)
        marks["deepseek/deepseek-v4-flash"] = "QUARANTINED"
        eligible = routing.eligible_models(
            inputs(models=models, qualification=marks), "CHEAP_MECHANICAL", "openrouter"
        )
        self.assertNotIn("deepseek/deepseek-v4-flash", [m.id for m in eligible])

    def test_verdicts_survive_a_catalogue_refresh(self) -> None:
        """36. A refresh must not silently re-promote or demote anything."""
        first = catalog.merge_qualification(
            [model("vendor/m", "openrouter")], {"models": {}}
        )
        first["models"]["vendor/m"]["qualification"] = "QUALIFIED"
        second = catalog.merge_qualification([model("vendor/m", "openrouter")], first)
        self.assertEqual(second["models"]["vendor/m"]["qualification"], "QUALIFIED")

    def test_a_model_that_leaves_the_catalogue_is_marked_absent(self) -> None:
        first = catalog.merge_qualification(
            [model("vendor/gone", "openrouter")], {"models": {}}
        )
        second = catalog.merge_qualification([], first)
        self.assertTrue(second["models"]["vendor/gone"]["absent"])
        self.assertEqual(
            catalog.models_from_state(second), [], "absent models must not route"
        )

    def test_deprecated_model_is_quarantined_automatically(self) -> None:
        entry = {"id": "vendor/old", "expiration_date": "2026-01-01"}
        normalised = catalog.normalise(entry)
        assert normalised is not None
        merged = catalog.merge_qualification([normalised], {"models": {}})
        self.assertEqual(merged["models"]["vendor/old"]["qualification"], "QUARANTINED")

    def test_deprecated_model_is_filtered_from_routing(self) -> None:
        models = [
            *model_pool(),
            model("vendor/old", "openrouter", price_in=0.01, deprecated=True),
        ]
        eligible = routing.eligible_models(
            inputs(models=models, qualification=qualification(models)),
            "CHEAP_MECHANICAL",
            "openrouter",
        )
        self.assertNotIn("vendor/old", [m.id for m in eligible])

    def test_qualification_suite_scores_answers(self) -> None:
        probe = qualify.PROBES[0]
        self.assertTrue(qualify.score(probe, "CONFLICT: renaming is forbidden")[0])
        self.assertFalse(qualify.score(probe, "PROCEED")[0])

    def test_qualification_suite_rejects_scope_creep(self) -> None:
        probe = next(p for p in qualify.PROBES if p.name == "scope_discipline")
        self.assertTrue(qualify.score(probe, "README.md")[0])
        self.assertFalse(qualify.score(probe, "README.md, utils.py")[0])

    def test_qualification_probes_carry_no_real_data(self) -> None:
        """Qualification never runs against production youth data."""
        for probe in qualify.PROBES:
            lowered = probe.prompt.lower()
            for forbidden in ("r2.dev", "supabase.co", "sk-", "@gmail", "footage/"):
                self.assertNotIn(forbidden, lowered, probe.name)

    def test_capability_filters_reject_undersized_models(self) -> None:
        small = [model("vendor/tiny", "openrouter", context=8_000, price_in=0.01)]
        eligible = routing.eligible_models(
            inputs(models=small, qualification=qualification(small)),
            "ROUTINE_CODING",
            "openrouter",
        )
        self.assertEqual(eligible, [])

    def test_capability_filters_reject_models_without_tools(self) -> None:
        toolless = [model("vendor/chat", "openrouter", tools=False, price_in=0.01)]
        eligible = routing.eligible_models(
            inputs(models=toolless, qualification=qualification(toolless)),
            "ROUTINE_CODING",
            "openrouter",
        )
        self.assertEqual(eligible, [])

    def test_price_ceiling_excludes_expensive_models_from_cheap_classes(self) -> None:
        pricey = [model("vendor/lux", "openrouter", price_in=25.0)]
        eligible = routing.eligible_models(
            inputs(models=pricey, qualification=qualification(pricey)),
            "CHEAP_MECHANICAL",
            "openrouter",
        )
        self.assertEqual(eligible, [])


class TestIndependentReview(unittest.TestCase):
    """57. The writer is never the only judge of its own work."""

    def test_reviewer_comes_from_a_different_provider(self) -> None:
        routing_inputs = inputs()
        current = classification("backend", "COMPLEX")
        writer = routing.select(routing_inputs, current)
        reviewer = routing.select_reviewer(routing_inputs, current, writer)
        self.assertNotEqual(
            policy()["lanes"][writer.lane]["provider"],
            policy()["lanes"][reviewer.lane]["provider"],
        )

    def test_frontend_work_still_gets_a_non_openai_reviewer(self) -> None:
        routing_inputs = inputs()
        current = classification("frontend", "ROUTINE")
        writer = routing.select(routing_inputs, current)
        reviewer = routing.select_reviewer(routing_inputs, current, writer)
        self.assertEqual(writer.lane, "codex_api")
        self.assertNotEqual(reviewer.lane, "codex_api")

    def test_a_reviewer_may_review_work_it_could_not_write(self) -> None:
        """Claude may not write UI, but it may review it."""
        routing_inputs = inputs()
        current = classification("frontend", "ROUTINE")
        reviewer = routing.select(routing_inputs, current, purpose="review")
        self.assertIn(reviewer.lane, policy()["lanes"])


class TestNotificationSafety(unittest.TestCase):
    """58-59. The feed is useful and never leaks a credential."""

    def test_events_are_formatted_with_a_marker(self) -> None:
        text = notify.format_event("merge", "Task 14 merged", {"pr": 42})
        self.assertTrue(text.startswith("✅"))
        self.assertIn("Task 14 merged", text)
        self.assertIn("pr: 42", text)

    def test_secrets_are_redacted(self) -> None:
        samples = (
            "sk-or-v1-0123456789abcdef0123",
            "ghp_0123456789abcdef0123456789abcdef0123",
            "OPENAI_API_KEY=sk-proj-abcdefghijklmnop",
            "github_pat_11ABCDEFG0123456789abcdefgh",
        )
        for sample in samples:
            redacted = notify.redact(f"failure while calling {sample}")
            self.assertNotIn(sample, redacted, sample)
            self.assertIn(notify.REDACTED, redacted)

    def test_redaction_applies_to_details_as_well_as_headlines(self) -> None:
        text = notify.format_event(
            "blocked",
            "auth failed",
            {"detail": "token=ghp_0123456789abcdef0123456789abcdef"},
        )
        self.assertNotIn("ghp_", text)

    def test_ordinary_text_survives_redaction(self) -> None:
        message = "Task 14 needs docs/03-schema.md and migration 0007."
        self.assertEqual(notify.redact(message), message)


class TestRealBacklogRouting(unittest.TestCase):
    """Routing the actual next task, end to end."""

    def test_task_14_routes_to_a_lane_allowed_to_write_both_halves(self) -> None:
        current = classify.classify(real_backlog().tasks[14])
        chosen = routing.select(inputs(), current)
        self.assertEqual(current.category, "mixed")
        lane = policy()["lanes"][chosen.lane]
        self.assertTrue(lane["may_write_frontend"])

    def test_task_18_player_ui_never_routes_to_claude(self) -> None:
        current = classify.classify(real_backlog().tasks[18])
        chosen = routing.select(inputs(), current)
        self.assertEqual(chosen.lane, "codex_api")

    def test_task_17_export_is_critical_and_well_resourced(self) -> None:
        current = classify.classify(real_backlog().tasks[17])
        chosen = routing.select(inputs(), current)
        self.assertEqual(current.complexity, "CRITICAL")
        self.assertIn(
            chosen.capability_class, ("FRONTIER_REASONING", "VISUAL_FRONTEND")
        )

    def test_replacing_the_catalogue_does_not_change_policy_outcomes(self) -> None:
        """Routing is by class, so a future model list still obeys the rules."""
        future = [
            model("anthropic/claude-next", "claude_subscription", price_in=0.3),
            model("openai/gpt-next", "codex_api", price_in=0.4, vision=True),
            model("deepseek/deepseek-v9", "openrouter", price_in=0.02),
        ]
        routing_inputs = inputs(models=future, qualification=qualification(future))
        # Names the orchestrator has never seen still land in the right lane.
        frontend = routing.select(routing_inputs, classification("frontend", "ROUTINE"))
        self.assertEqual(frontend.model, "openai/gpt-next")
        backend = routing.select(routing_inputs, classification("backend", "TRIVIAL"))
        self.assertEqual(backend.model, "anthropic/claude-next")
        overflow = routing.select(
            routing_inputs,
            classification("backend", "TRIVIAL"),
            exclude_lanes=frozenset({"claude_subscription", "codex_api"}),
        )
        self.assertEqual(overflow.model, "deepseek/deepseek-v9")

    def test_subscription_capacity_is_preferred_over_a_cheaper_api_lane(self) -> None:
        """Already-paid capacity beats a lower per-token price on a metered lane.

        Spending API money while subscription allowance sits unused is the more
        expensive choice, not the cheaper one, so lane priority decides first
        and price decides within a lane.
        """
        pool = [
            model("anthropic/claude-haiku-4.5", "claude_subscription", price_in=1.0),
            model("deepseek/deepseek-v4-flash", "openrouter", price_in=0.01),
        ]
        routing_inputs = inputs(models=pool, qualification=qualification(pool))
        chosen = routing.select(routing_inputs, classification("backend", "TRIVIAL"))
        self.assertEqual(chosen.lane, "claude_subscription")
        self.assertEqual(policy()["lanes"][chosen.lane]["billing"], "subscription")
        self.assertEqual(
            chosen.fallbacks, (("openrouter", "deepseek/deepseek-v4-flash"),)
        )


if __name__ == "__main__":
    unittest.main()
