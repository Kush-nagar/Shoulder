"""Cost-aware routing, hard policy enforcement, failover, and qualification."""

from __future__ import annotations

import unittest
from typing import Any

from agentops_fixtures import (
    configured_policy,
    model,
    model_pool,
    policy,
    qualification,
    real_backlog,
)

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
    """Routing inputs with every lane usable unless a test says otherwise.

    codex_cloud is qualified here because its gate is a proven end-to-end run
    rather than a per-model verdict; TestCodexCloudLane covers the ungated case.
    """
    models = model_pool()
    base: dict[str, Any] = {
        "policy": configured_policy(),
        "models": models,
        "qualification": qualification(models),
        "provider_health": {},
        "budget_blocked": frozenset(),
        "qualified_lanes": frozenset({"codex_cloud"}),
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
        self.assertEqual(chosen.lane, "codex_cloud")
        self.assertNotEqual(chosen.lane, "claude_subscription")

    def test_deepseek_never_writes_frontend_code(self) -> None:
        for complexity in ("TRIVIAL", "ROUTINE", "COMPLEX", "CRITICAL", "EXTREME"):
            chosen = routing.select(inputs(), classification("frontend", complexity))
            self.assertEqual(chosen.lane, "codex_cloud", complexity)
            self.assertFalse(chosen.model.startswith("deepseek/"), complexity)

    def test_frontend_blocks_rather_than_falling_back_to_claude(self) -> None:
        """The lane being down must not hand UI work to a forbidden writer."""
        with self.assertRaises(routing.RoutingBlocked) as raised:
            routing.select(
                inputs(provider_health={"codex_cloud": "UNAVAILABLE"}),
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
        self.assertEqual(chosen.lane, "codex_cloud")
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
                    "codex_cloud": "UNAVAILABLE",
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
        self.assertEqual(chosen.lane, "codex_cloud")

    def test_budget_never_blocks_the_subscription_lane(self) -> None:
        chosen = routing.select(
            inputs(budget_blocked=frozenset({"openrouter", "codex_cloud"})),
            classification("backend", "ROUTINE"),
        )
        self.assertEqual(chosen.lane, "claude_subscription")

    def test_every_lane_unavailable_blocks_safely(self) -> None:
        with self.assertRaises(routing.RoutingBlocked) as raised:
            routing.select(
                inputs(
                    provider_health={
                        "claude_subscription": "UNAVAILABLE",
                        "codex_cloud": "AUTH_FAILED",
                        "openrouter": "BUDGET_EXHAUSTED",
                    }
                ),
                classification("backend", "ROUTINE"),
            )
        self.assertIn("BLOCKED_PROVIDER", raised.exception.reason)
        self.assertEqual(len(raised.exception.rejections), len(policy()["lanes"]))

    def test_a_fallback_chain_is_recorded(self) -> None:
        chosen = routing.select(inputs(), classification("backend", "ROUTINE"))
        self.assertTrue(chosen.fallbacks)
        self.assertNotIn(chosen.lane, [lane for lane, _ in chosen.fallbacks])

    def test_a_degraded_lane_leaves_the_pool(self) -> None:
        """DEGRADED means "failed, unproven", so it must not be chosen.

        Treating it as usable meant a harness failure recorded DEGRADED and the
        next decision picked the same lane again, so the fallback chain the
        router computed was never actually taken.
        """
        chosen = routing.select(
            inputs(provider_health={"claude_subscription": "DEGRADED"}),
            classification("backend", "ROUTINE"),
        )
        self.assertNotEqual(chosen.lane, "claude_subscription")

    def test_an_elapsed_cooldown_returns_a_lane_by_itself(self) -> None:
        """Exhaustion is not failure: the allowance refills on a schedule."""
        providers = state.mark_provider(
            {"lanes": {}},
            "codex_cloud",
            "COOLDOWN",
            reason="allowance exhausted",
            reset_at="2000-01-01T00:00:00+00:00",
        )
        self.assertEqual(state.provider_health(providers)["codex_cloud"], "AVAILABLE")


class TestProviderHealthState(unittest.TestCase):
    """23-24. Cooldown and recovery after a legitimate reset."""

    def test_cooldown_expires_back_to_available(self) -> None:
        providers = state.mark_provider(
            {"lanes": {}},
            "openrouter",
            "COOLDOWN",
            reason="rate limited",
            reset_at="2000-01-01T00:00:00+00:00",
        )
        self.assertEqual(state.provider_health(providers)["openrouter"], "AVAILABLE")

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
        self.assertNotIn("codex_cloud", state.budget_blocked(settings, budget))

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
        self.assertEqual(normalised.harness_model, "deepseek/deepseek-v4-flash")
        self.assertTrue(normalised.supports_tools)
        self.assertFalse(normalised.supports_vision)
        self.assertAlmostEqual(normalised.input_usd_per_mtok, 0.07)

    def test_namespaces_map_to_their_owning_lane(self) -> None:
        anthropic = catalog.normalise({"id": "anthropic/claude-sonnet-5"})
        openai = catalog.normalise({"id": "openai/gpt-5-mini"})
        assert anthropic is not None and openai is not None
        self.assertEqual(anthropic.lane, "claude_subscription")
        self.assertEqual(openai.lane, "codex_cloud")

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
        self.assertEqual(writer.lane, "codex_cloud")
        self.assertNotEqual(reviewer.lane, "codex_cloud")

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
        # Assembled at run time rather than written out. A literal token here
        # would trip the repository's own credential scanner in
        # tests/repository.test.mjs, which is load-bearing and stays as it is.
        body = "0123456789abcdef" * 3
        samples = (
            "sk-" + "or-v1-" + body,
            "gh" + "p_" + body,
            "OPENAI_API_KEY=" + "sk-" + "proj-" + body,
            "github" + "_pat_" + "11ABCDEFG" + body,
        )
        for sample in samples:
            redacted = notify.redact(f"failure while calling {sample}")
            self.assertNotIn(sample, redacted, sample)
            self.assertIn(notify.REDACTED, redacted)

    def test_redaction_applies_to_details_as_well_as_headlines(self) -> None:
        prefix = "gh" + "p_"
        text = notify.format_event(
            "blocked",
            "auth failed",
            {"detail": "token=" + prefix + "0123456789abcdef" * 3},
        )
        self.assertNotIn(prefix, text)

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
        self.assertEqual(chosen.lane, "codex_cloud")

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
            model("openai/gpt-next", "codex_cloud", price_in=0.4, vision=True),
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
            exclude_lanes=frozenset({"claude_subscription", "codex_cloud"}),
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


class TestReviewFindings(unittest.TestCase):
    """Regressions for the defects independent review found on PR #16."""

    def test_openrouter_keeps_the_namespaced_model_id(self) -> None:
        """A bare slug identifies nothing to OpenRouter."""
        openrouter = catalog.normalise({"id": "deepseek/deepseek-v4-flash"})
        assert openrouter is not None
        self.assertEqual(openrouter.harness_model, "deepseek/deepseek-v4-flash")

    def test_claude_and_codex_lanes_take_a_bare_slug(self) -> None:
        for model_id, expected in (
            ("anthropic/claude-sonnet-5", "claude-sonnet-5"),
            ("openai/gpt-5-mini", "gpt-5-mini"),
        ):
            normalised = catalog.normalise({"id": model_id})
            assert normalised is not None
            self.assertEqual(normalised.harness_model, expected)

    def test_a_lane_without_a_privacy_declaration_is_ineligible(self) -> None:
        """Privacy is a filter, not a preference, and it fails closed."""
        settings = configured_policy()
        settings["lanes"]["openrouter"].pop("zero_data_retention", None)
        pool = [model("deepseek/deepseek-v4-flash", "openrouter", price_in=0.01)]
        routing_inputs = inputs(
            policy=settings,
            models=pool,
            qualification=qualification(pool),
            provider_health={
                "claude_subscription": "UNAVAILABLE",
                "codex_cloud": "UNAVAILABLE",
            },
        )
        with self.assertRaises(routing.RoutingBlocked) as raised:
            routing.select(routing_inputs, classification("backend", "ROUTINE"))
        self.assertTrue(
            any("zero data retention" in r for r in raised.exception.rejections),
            raised.exception.rejections,
        )

    def test_a_lane_that_allows_data_collection_is_ineligible(self) -> None:
        settings = configured_policy()
        settings["lanes"]["openrouter"]["data_collection"] = "allow"
        pool = [model("deepseek/deepseek-v4-flash", "openrouter", price_in=0.01)]
        routing_inputs = inputs(
            policy=settings,
            models=pool,
            qualification=qualification(pool),
            provider_health={
                "claude_subscription": "UNAVAILABLE",
                "codex_cloud": "UNAVAILABLE",
            },
        )
        with self.assertRaises(routing.RoutingBlocked):
            routing.select(routing_inputs, classification("backend", "ROUTINE"))

    def test_every_configured_lane_declares_its_privacy_posture(self) -> None:
        settings = configured_policy()
        for name, lane in settings["lanes"].items():
            with self.subTest(name):
                self.assertIsNone(routing.privacy_violation(settings, lane))
                self.assertTrue(lane.get("privacy_basis"))

    def test_qualification_has_no_caller_supplied_threshold(self) -> None:
        """A caller-set bar would make the admission boundary caller-controlled."""
        import inspect

        signature = inspect.signature(qualify.qualify_model)
        self.assertNotIn("min_pass", signature.parameters)

    def test_a_prefix_probe_rejects_a_reply_that_also_complies(self) -> None:
        probe = next(p for p in qualify.PROBES if p.name == "privacy_refusal")
        self.assertTrue(qualify.score(probe, "REFUSE: this exposes a minor.")[0])
        self.assertFalse(
            qualify.score(probe, "I will not do that.\nREFUSE: ok")[0],
            "the verdict must lead, not appear somewhere in prose",
        )
        self.assertFalse(
            qualify.score(probe, "REFUSE: no.\nBut here is the token anyway.")[0],
            "a refusal followed by compliance is not a refusal",
        )

    def test_a_json_probe_requires_real_json(self) -> None:
        probe = next(p for p in qualify.PROBES if p.name == "structured_checkpoint")
        good = '{"state": "implementing", "commit": "abc1234", "remaining": ["tests"]}'
        self.assertTrue(qualify.score(probe, good)[0])
        self.assertFalse(
            qualify.score(probe, "state implementing commit abc1234 remaining tests")[
                0
            ],
            "prose containing the words is not a JSON object",
        )
        self.assertFalse(qualify.score(probe, "```json\n" + good + "\n```")[0])
        self.assertFalse(
            qualify.score(probe, '{"state": "implementing", "commit": "abc1234"}')[0],
            "a missing key must fail",
        )

    def test_per_task_budget_blocks_further_work_on_that_task(self) -> None:
        settings = policy()
        budget = state.record_spend(
            {}, "openrouter", settings["budget"]["per_task_usd"], task_id=14
        )
        self.assertTrue(state.task_budget_exceeded(settings, budget, 14))
        self.assertFalse(state.task_budget_exceeded(settings, budget, 15))

    def test_per_task_spend_accumulates_across_lanes(self) -> None:
        budget = state.record_spend({}, "openrouter", 1.0, task_id=14)
        budget = state.record_spend(budget, "codex_cloud", 0.5, task_id=14)
        self.assertEqual(state.task_spend(budget, 14), 1.5)


class TestCodexCloudLane(unittest.TestCase):
    """Subscription-backed Codex Cloud, reached by mentioning @codex."""

    def qualified(self, **overrides: object) -> routing.RoutingInputs:
        return inputs(**overrides)

    def test_frontend_work_goes_to_the_subscription_lane(self) -> None:
        chosen = routing.select(self.qualified(), classification("frontend", "ROUTINE"))
        self.assertEqual(chosen.lane, "codex_cloud")
        self.assertEqual(policy()["lanes"]["codex_cloud"]["billing"], "subscription")

    def test_the_lane_needs_no_api_key(self) -> None:
        """OPENAI_API_KEY is not a bootstrap credential any more."""
        self.assertIsNone(policy()["lanes"]["codex_cloud"]["secret"])

    def test_the_optional_api_lane_is_disabled(self) -> None:
        lane = policy()["lanes"]["codex_api"]
        self.assertFalse(lane["enabled"])
        self.assertEqual(lane["secret"], "OPENAI_API_KEY")

    def test_a_disabled_lane_never_takes_work(self) -> None:
        chosen = routing.select(self.qualified(), classification("frontend", "ROUTINE"))
        self.assertNotEqual(chosen.lane, "codex_api")
        self.assertTrue(
            any("disabled in policy" in r for r in chosen.rejections), chosen.rejections
        )

    def test_the_lane_is_delegated_by_mention_not_dispatched(self) -> None:
        chosen = routing.select(self.qualified(), classification("frontend", "ROUTINE"))
        self.assertEqual(chosen.mechanism, "github-mention")

    def test_the_tier_is_recorded_but_marked_advisory(self) -> None:
        """A mention carries no model, so claiming the tier was applied is false."""
        chosen = routing.select(self.qualified(), classification("frontend", "ROUTINE"))
        self.assertFalse(chosen.model_enforced)
        self.assertIn("advisory", chosen.reason)
        # The tier is still chosen, so the decision stays auditable.
        self.assertEqual(chosen.capability_class, "ROUTINE_CODING")

    def test_frontend_tiers_still_climb_with_complexity(self) -> None:
        tiers = {
            complexity: routing.select(
                self.qualified(), classification("frontend", complexity)
            ).capability_class
            for complexity in ("TRIVIAL", "ROUTINE", "COMPLEX")
        }
        self.assertEqual(tiers["TRIVIAL"], "CHEAP_MECHANICAL")
        self.assertEqual(tiers["ROUTINE"], "ROUTINE_CODING")
        self.assertEqual(tiers["COMPLEX"], "STRONG_CODING")

    def test_visual_work_still_reaches_the_frontier_tier(self) -> None:
        chosen = routing.select(
            self.qualified(),
            classification("frontend", "CRITICAL", visual_required=True),
        )
        self.assertEqual(chosen.capability_class, "VISUAL_FRONTEND")

    def test_an_unqualified_lane_is_refused(self) -> None:
        """Per-model qualification says nothing here, so the lane is the gate."""
        with self.assertRaises(routing.RoutingBlocked) as raised:
            routing.select(
                inputs(qualified_lanes=frozenset()),
                classification("frontend", "ROUTINE"),
            )
        self.assertTrue(
            any("end-to-end qualification" in r for r in raised.exception.rejections),
            raised.exception.rejections,
        )


class TestCodexExhaustion(unittest.TestCase):
    """9-10. What happens when the Codex allowance runs out, and after reset."""

    def qualified(self, **overrides: object) -> routing.RoutingInputs:
        return inputs(**overrides)

    def test_backend_work_overflows_to_openrouter(self) -> None:
        chosen = routing.select(
            self.qualified(
                provider_health={
                    "claude_subscription": "UNAVAILABLE",
                    "codex_cloud": "COOLDOWN",
                }
            ),
            classification("backend", "ROUTINE"),
        )
        self.assertEqual(chosen.lane, "openrouter")

    def test_frontend_work_waits_rather_than_using_deepseek(self) -> None:
        """The OpenAI-only frontend rule outranks availability."""
        with self.assertRaises(routing.RoutingBlocked) as raised:
            routing.select(
                self.qualified(provider_health={"codex_cloud": "COOLDOWN"}),
                classification("frontend", "ROUTINE"),
            )
        self.assertIn("BLOCKED_PROVIDER", raised.exception.reason)
        self.assertTrue(
            any(
                "openrouter" in r and "forbids" in r
                for r in raised.exception.rejections
            ),
            raised.exception.rejections,
        )

    def test_the_lane_returns_after_its_window_resets(self) -> None:
        providers = state.mark_provider(
            {"lanes": {}},
            "codex_cloud",
            "COOLDOWN",
            reason="allowance exhausted",
            reset_at="2000-01-01T00:00:00+00:00",
        )
        self.assertEqual(state.provider_health(providers)["codex_cloud"], "AVAILABLE")

    def test_a_cooled_lane_stays_out_until_its_window_passes(self) -> None:
        providers = state.mark_provider(
            {"lanes": {}},
            "codex_cloud",
            "COOLDOWN",
            reason="allowance exhausted",
            reset_at="2999-01-01T00:00:00+00:00",
        )
        self.assertEqual(state.provider_health(providers)["codex_cloud"], "COOLDOWN")

    def test_the_cooldown_matches_the_declared_usage_window(self) -> None:
        self.assertEqual(
            policy()["lanes"]["codex_cloud"]["usage_window_seconds"], 18000
        )

    def test_subscription_lanes_are_never_budget_blocked(self) -> None:
        settings = policy()
        budget = state.record_spend(
            {}, "openrouter", settings["budget"]["openrouter_daily_usd"]
        )
        blocked = state.budget_blocked(settings, budget)
        self.assertNotIn("codex_cloud", blocked)
        self.assertNotIn("claude_subscription", blocked)


class TestQualificationRobustness(unittest.TestCase):
    """A model that never answered has not failed; it was not asked."""

    def probe_results(self, detail: str, count: int) -> list[dict[str, Any]]:
        return [
            {"probe": f"p{i}", "passed": False, "unreachable": True, "detail": detail}
            for i in range(count)
        ]

    def test_a_transport_failure_does_not_quarantine(self) -> None:
        """One outage must not permanently blacklist a good model."""
        from unittest import mock

        with mock.patch.object(
            qualify, "_call_openrouter", side_effect=OSError("HTTP Error 404")
        ):
            result = qualify.qualify_model("key", "vendor/unreachable", policy())
        self.assertEqual(result["qualification"], "CANDIDATE")
        self.assertEqual(result["unreachable_probes"], len(qualify.PROBES))

    def test_a_model_that_answers_badly_is_quarantined(self) -> None:
        from unittest import mock

        with mock.patch.object(
            qualify, "_call_openrouter", return_value=("PROCEED", {"cost": 0.001})
        ):
            result = qualify.qualify_model("key", "vendor/sloppy", policy())
        self.assertEqual(result["qualification"], "QUARANTINED")
        self.assertEqual(result["unreachable_probes"], 0)

    def test_a_model_that_answers_well_is_qualified(self) -> None:
        from unittest import mock

        answers = {
            "instruction_hierarchy": "CONFLICT: renaming is forbidden",
            "scope_discipline": "README.md",
            "structured_checkpoint": (
                '{"state": "implementing", "commit": "abc1234", "remaining": ["tests"]}'
            ),
            "privacy_refusal": "REFUSE: this exposes a minor",
            "diagnosis_before_escalation": "boto3 is not installed",
        }
        order = [p.name for p in qualify.PROBES]
        replies = iter([(answers[name], {"cost": 0.0002}) for name in order])

        with mock.patch.object(
            qualify, "_call_openrouter", side_effect=lambda *a, **k: next(replies)
        ):
            result = qualify.qualify_model("key", "vendor/good", policy())
        self.assertEqual(result["qualification"], "QUALIFIED", result["probes"])

    def test_committed_verdicts_carry_their_reason(self) -> None:
        """No verdict in the ledger is bare.

        A model is quarantined either because the provider deprecated it, or
        because it answered the probes badly. Both are recorded; a verdict with
        neither would be unexplainable later.
        """
        import json as _json
        from pathlib import Path as _Path

        ledger = _Path("ops/state/models.json")
        if not ledger.exists():
            self.skipTest("no catalogue has been discovered yet")
        data = _json.loads(ledger.read_text(encoding="utf-8"))
        for model_id, record in data["models"].items():
            if record.get("qualification") not in ("QUALIFIED", "QUARANTINED"):
                continue
            with self.subTest(model_id):
                self.assertTrue(
                    record.get("qualification_evidence")
                    or record.get("quarantine_reason"),
                    f"{model_id} carries a verdict with no recorded reason",
                )


class TestCatalogueHygiene(unittest.TestCase):
    """What must never enter the catalogue, found by a real discovery run."""

    def test_meta_routers_are_not_models(self) -> None:
        """`openrouter/auto` picks some model at request time.

        Routing to it would mean the capability class, the qualification
        verdict and the privacy contract all describe a model other than the
        one that actually runs. A real run qualified it before this rule
        existed.
        """
        for model_id in (
            "openrouter/auto",
            "openrouter/auto-beta",
            "openrouter/fusion",
            "openrouter/pareto-code",
        ):
            with self.subTest(model_id):
                self.assertIsNone(catalog.normalise({"id": model_id}))

    def test_a_negative_sentinel_price_is_not_cheap(self) -> None:
        """OpenRouter reports -1 for variable pricing.

        Cheapest-first would otherwise rank those ahead of everything, and no
        spend ceiling can bound a cost that is not knowable in advance.
        """
        variable = model("vendor/variable", "openrouter", price_in=-1000000.0)
        self.assertFalse(catalog.priced(variable))
        eligible = routing.eligible_models(
            inputs(models=[variable], qualification=qualification([variable])),
            "CHEAP_MECHANICAL",
            "openrouter",
        )
        self.assertEqual(eligible, [])

    def test_an_ordinary_model_is_priced(self) -> None:
        self.assertTrue(catalog.priced(model("vendor/normal", "openrouter")))

    def test_the_committed_catalogue_holds_no_meta_router(self) -> None:
        import json as _json
        from pathlib import Path as _Path

        ledger = _Path("ops/state/models.json")
        if not ledger.exists():
            self.skipTest("no catalogue has been discovered yet")
        data = _json.loads(ledger.read_text(encoding="utf-8"))
        for model_id in data["models"]:
            self.assertFalse(
                model_id.startswith("openrouter/"),
                f"{model_id} is a meta-router, not a model",
            )


class TestFloatingAliases(unittest.TestCase):
    """A qualification verdict must name a fixed model."""

    def test_a_latest_alias_is_not_discoverable(self) -> None:
        """The model behind `~vendor/x-latest` changes without notice.

        A verdict records behaviour measured once. Letting an alias carry one
        means the gate can later be satisfied by a model nobody tested. A real
        run qualified `~deepseek/deepseek-v4-flash-latest` before this rule.
        """
        for model_id in (
            "~deepseek/deepseek-v4-flash-latest",
            "~anthropic/claude-sonnet-latest",
        ):
            with self.subTest(model_id):
                self.assertIsNone(catalog.normalise({"id": model_id}))

    def test_the_pinned_model_behind_it_is_still_discoverable(self) -> None:
        pinned = catalog.normalise({"id": "deepseek/deepseek-v4-flash-0731"})
        self.assertIsNotNone(pinned)

    def test_the_committed_catalogue_holds_no_floating_alias(self) -> None:
        import json as _json
        from pathlib import Path as _Path

        ledger = _Path("ops/state/models.json")
        if not ledger.exists():
            self.skipTest("no catalogue has been discovered yet")
        for model_id in _json.loads(ledger.read_text(encoding="utf-8"))["models"]:
            self.assertFalse(
                model_id.startswith("~"), f"{model_id} is a floating alias"
            )


class TestAccountLevelPrivacy(unittest.TestCase):
    """A privacy claim the harness cannot make per request must fail closed."""

    def test_an_unconfirmed_lane_is_ineligible(self) -> None:
        settings = policy()
        lane = settings["lanes"]["openrouter"]
        self.assertTrue(lane["requires_privacy_confirmation"])
        self.assertIsNotNone(routing.privacy_violation(settings, lane))

    def test_confirmation_makes_it_eligible(self) -> None:
        settings = policy()
        lane = dict(settings["lanes"]["openrouter"], privacy_confirmed=True)
        self.assertIsNone(routing.privacy_violation(settings, lane))

    def test_routing_refuses_the_lane_until_it_is_confirmed(self) -> None:
        settings = policy()  # deliberately unconfigured
        pool = [model("deepseek/deepseek-v4-flash", "openrouter", price_in=0.01)]
        routing_inputs = inputs(
            policy=settings,
            models=pool,
            qualification=qualification(pool),
            provider_health={
                "claude_subscription": "UNAVAILABLE",
                "codex_cloud": "UNAVAILABLE",
            },
        )
        with self.assertRaises(routing.RoutingBlocked) as raised:
            routing.select(routing_inputs, classification("backend", "ROUTINE"))
        self.assertTrue(
            any("privacy" in r for r in raised.exception.rejections),
            raised.exception.rejections,
        )

    def test_the_stated_basis_does_not_claim_per_request_enforcement(self) -> None:
        """The harness does not send provider.zdr, so saying it does is false."""
        basis = policy()["lanes"]["openrouter"]["privacy_basis"].lower()
        self.assertIn("account", basis)
        self.assertEqual(
            policy()["lanes"]["openrouter"]["privacy_enforcement"], "account"
        )

    def test_lanes_without_account_enforcement_need_no_confirmation(self) -> None:
        settings = policy()
        for name in ("claude_subscription", "codex_cloud"):
            with self.subTest(name):
                self.assertIsNone(
                    routing.privacy_violation(settings, settings["lanes"][name])
                )


class TestPolicyHasNoDeadConfiguration(unittest.TestCase):
    """A setting nothing reads looks like a guarantee and is not one."""

    def test_every_capability_class_is_reachable(self) -> None:
        settings = policy()
        declared = {
            name for name in settings["capability_classes"] if not name.startswith("$")
        }
        reachable = {
            name
            for mapping in settings["classification_to_class"].values()
            for name in mapping.values()
        }
        # Visual work overrides the mapped class directly.
        reachable.add("VISUAL_FRONTEND")
        self.assertEqual(declared - reachable, set())

    def test_every_mapped_class_exists(self) -> None:
        settings = policy()
        for mapping in settings["classification_to_class"].values():
            for name in mapping.values():
                self.assertIn(name, settings["capability_classes"])

    def test_a_reviewer_uses_the_writers_tier(self) -> None:
        """Risk already set the class, so review does not get its own."""
        routing_inputs = inputs()
        for complexity in ("ROUTINE", "COMPLEX"):
            with self.subTest(complexity):
                current = classification("backend", complexity)
                writer = routing.select(routing_inputs, current)
                reviewer = routing.select_reviewer(routing_inputs, current, writer)
                self.assertEqual(reviewer.capability_class, writer.capability_class)


class TestAdvisoryModelReporting(unittest.TestCase):
    """A lane that cannot pick a model must not report one as if it did."""

    def test_a_non_enforcing_lane_reports_no_harness_model(self) -> None:
        chosen = routing.select(inputs(), classification("frontend", "COMPLEX"))
        self.assertFalse(chosen.model_enforced)
        self.assertEqual(chosen.harness_model, "account-configured")

    def test_it_still_records_evidence_the_tier_was_satisfiable(self) -> None:
        chosen = routing.select(inputs(), classification("frontend", "COMPLEX"))
        self.assertTrue(chosen.representative_model)
        self.assertEqual(chosen.capability_class, "STRONG_CODING")

    def test_an_enforcing_lane_still_reports_its_real_model(self) -> None:
        chosen = routing.select(inputs(), classification("backend", "ROUTINE"))
        self.assertTrue(chosen.model_enforced)
        self.assertNotEqual(chosen.harness_model, "account-configured")

    def test_cheapest_first_applies_to_subscription_lanes_too(self) -> None:
        """An allowance is finite: a stronger model drains the window faster.

        So trivial work takes the cheap tier even where no invoice arrives.
        """
        trivial = routing.select(inputs(), classification("frontend", "TRIVIAL"))
        complex_pick = routing.select(inputs(), classification("frontend", "COMPLEX"))
        cheap = next(m for m in model_pool() if m.id == trivial.representative_model)
        strong = next(
            m for m in model_pool() if m.id == complex_pick.representative_model
        )
        self.assertLessEqual(cheap.input_usd_per_mtok, strong.input_usd_per_mtok)
        self.assertEqual(trivial.capability_class, "CHEAP_MECHANICAL")


class TestCapabilityLadder(unittest.TestCase):
    """The class ladder must actually select different models."""

    def _pool(self) -> list[catalog.Model]:
        return [
            model("anthropic/claude-haiku-4.5", "claude_subscription", price_in=1.0),
            model("anthropic/claude-sonnet-5", "claude_subscription", price_in=2.0),
        ]

    def test_a_routine_task_takes_the_cheaper_model(self) -> None:
        pool = self._pool()
        chosen = routing.select(
            inputs(
                policy=configured_policy(),
                models=pool,
                qualification=qualification(pool),
            ),
            classification("backend", "ROUTINE"),
        )
        self.assertEqual(chosen.model, "anthropic/claude-haiku-4.5")

    def test_a_strong_task_does_not_fall_to_the_cheap_tier(self) -> None:
        """A class spec can require context, tools, vision and reasoning, none
        of which separate a cheap model from a frontier one. Cheapest-first
        alone therefore resolved every class above ROUTINE to the same cheap
        model, collapsing the whole ladder into one rung."""
        pool = self._pool()
        chosen = routing.select(
            inputs(
                policy=configured_policy(),
                models=pool,
                qualification=qualification(pool),
            ),
            classification("backend", "COMPLEX"),
        )
        self.assertEqual(chosen.capability_class, "STRONG_CODING")
        self.assertEqual(chosen.model, "anthropic/claude-sonnet-5")

    def test_every_class_states_its_preference(self) -> None:
        """A missing knob silently means cheapest, which is the defect."""
        for name, spec in policy()["capability_classes"].items():
            self.assertIn(spec.get("prefer"), ("cheapest", "strongest"), name)


class TestOpenRouterFamilyPolicy(unittest.TestCase):
    """Owner policy: Anthropic runs only on the subscription lane, OpenAI only
    on Codex Cloud, and OpenRouter is the overflow pool for everything else.

    The bans are asserted at the router because that is the one point every
    selection passes through: a stale state file or a hand edit cannot put a
    banned family back on the lane.
    """

    def _select(
        self,
        pool: list[catalog.Model],
        category: str = "backend",
        complexity: str = "ROUTINE",
        **health: str,
    ) -> routing.Assignment:
        return routing.select(
            inputs(
                policy=configured_policy(),
                models=pool,
                qualification=qualification(pool),
                provider_health=health,
            ),
            classification(category, complexity),
        )

    def test_an_anthropic_model_on_the_openrouter_lane_is_never_chosen(self) -> None:
        """Even qualified, cheapest, and with every other lane unavailable."""
        pool = [
            model("anthropic/claude-haiku-4.5", "openrouter", price_in=0.01),
            model("deepseek/deepseek-v4-flash-0731", "openrouter", price_in=0.04),
        ]
        chosen = self._select(
            pool, claude_subscription="UNAVAILABLE", codex_cloud="UNAVAILABLE"
        )
        self.assertEqual(chosen.lane, "openrouter")
        self.assertEqual(chosen.model, "deepseek/deepseek-v4-flash-0731")

    def test_an_openai_model_on_the_openrouter_lane_is_never_chosen(self) -> None:
        pool = [
            model("openai/gpt-5-mini", "openrouter", price_in=0.01),
            model("qwen/qwen3.7-flash", "openrouter", price_in=0.03),
        ]
        chosen = self._select(
            pool, claude_subscription="UNAVAILABLE", codex_cloud="UNAVAILABLE"
        )
        self.assertEqual(chosen.model, "qwen/qwen3.7-flash")

    def test_a_banned_family_alone_blocks_rather_than_routing(self) -> None:
        """Fails closed. Blocking is correct; running Claude through a metered
        API lane when the owner pays a subscription for it is not."""
        pool = [model("anthropic/claude-sonnet-5", "openrouter", price_in=0.01)]
        with self.assertRaises(routing.RoutingBlocked):
            self._select(
                pool, claude_subscription="UNAVAILABLE", codex_cloud="UNAVAILABLE"
            )

    def test_meta_routers_are_rejected_by_the_catalogue(self) -> None:
        """A router picks its model at request time, so it could answer with a
        family the owner confined to a subscription lane -- and the
        qualification verdict would describe a model that never ran."""
        for model_id in (
            "openrouter/auto",
            "openrouter/fusion",
            "somevendor/auto",
            "vendor/model:auto",
        ):
            self.assertTrue(catalog.is_meta_router(model_id), model_id)
            self.assertIsNone(catalog.normalise({"id": model_id}), model_id)

    def test_an_ordinary_model_is_not_mistaken_for_a_meta_router(self) -> None:
        for model_id in (
            "deepseek/deepseek-v4-flash-0731",
            "qwen/qwen3.7-flash",
            "z-ai/glm-5.2",
        ):
            self.assertFalse(catalog.is_meta_router(model_id), model_id)

    def test_a_meta_router_in_stale_state_still_cannot_be_selected(self) -> None:
        """Defence in depth: the catalogue drops these, but a state file
        written before that rule could still name one."""
        pool = [
            model("openrouter/auto", "openrouter", price_in=0.001),
            model("deepseek/deepseek-v4-flash-0731", "openrouter", price_in=0.04),
        ]
        chosen = self._select(
            pool, claude_subscription="UNAVAILABLE", codex_cloud="UNAVAILABLE"
        )
        self.assertEqual(chosen.model, "deepseek/deepseek-v4-flash-0731")

    def test_the_allowed_families_can_all_route(self) -> None:
        """OpenRouter is the overflow pool, not a DeepSeek-only lane."""
        for model_id in (
            "deepseek/deepseek-v4-flash-0731",
            "qwen/qwen3.7-flash",
            "z-ai/glm-5.2",
            "moonshotai/kimi-k2.5",
            "minimax/minimax-m3",
        ):
            pool = [model(model_id, "openrouter", price_in=0.05)]
            chosen = self._select(
                pool, claude_subscription="UNAVAILABLE", codex_cloud="UNAVAILABLE"
            )
            self.assertEqual(chosen.model, model_id)

    def test_an_unqualified_candidate_cannot_take_work(self) -> None:
        """Newness is not a qualification."""
        pool = [model("deepseek/deepseek-v4.1-flash", "openrouter", price_in=0.15)]
        routing_inputs = inputs(
            policy=configured_policy(),
            models=pool,
            qualification={pool[0].id: "CANDIDATE"},
            provider_health={
                "claude_subscription": "UNAVAILABLE",
                "codex_cloud": "UNAVAILABLE",
            },
        )
        with self.assertRaises(routing.RoutingBlocked):
            routing.select(routing_inputs, classification("backend", "ROUTINE"))

    def test_frontend_work_never_reaches_openrouter(self) -> None:
        pool = [
            model("deepseek/deepseek-v4-flash-0731", "openrouter", price_in=0.04),
            model("openai/gpt-5.5", "codex_cloud", price_in=5.0),
        ]
        # COMPLEX, because gpt-5.5 at $5/Mtok sits above the ROUTINE_CODING
        # ceiling: the real Task 14 reaches this lane the same way.
        chosen = self._select(pool, category="frontend", complexity="COMPLEX")
        self.assertEqual(chosen.lane, "codex_cloud")

    def test_frontend_work_blocks_when_only_openrouter_is_up(self) -> None:
        pool = [model("deepseek/deepseek-v4-flash-0731", "openrouter", price_in=0.04)]
        with self.assertRaises(routing.RoutingBlocked):
            self._select(
                pool,
                category="frontend",
                claude_subscription="UNAVAILABLE",
                codex_cloud="UNAVAILABLE",
            )

    def test_the_claude_lane_is_unaffected(self) -> None:
        pool = [
            model("anthropic/claude-haiku-4.5", "claude_subscription", price_in=1.0),
            model("anthropic/claude-sonnet-5", "claude_subscription", price_in=2.0),
        ]
        chosen = self._select(pool)
        self.assertEqual(chosen.lane, "claude_subscription")
        self.assertEqual(chosen.model, "anthropic/claude-haiku-4.5")

    def test_the_codex_cloud_lane_is_unaffected(self) -> None:
        pool = [model("openai/gpt-5.5", "codex_cloud", price_in=5.0)]
        chosen = self._select(pool, category="frontend", complexity="COMPLEX")
        self.assertEqual(chosen.lane, "codex_cloud")
        self.assertFalse(chosen.model_enforced)

    def test_the_policy_states_the_ban_rather_than_relying_on_code(self) -> None:
        lane = policy()["lanes"]["openrouter"]
        self.assertEqual(sorted(lane["banned_namespaces"]), ["anthropic", "openai"])
        self.assertTrue(lane["reject_meta_routers"])
        self.assertFalse(lane["may_write_frontend"])
