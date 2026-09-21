"""Claude first, then an approved fallback, without losing the task.

The subscription is the preferred worker and stays preferred while it has
allowance. What was missing was the other half: when Claude Code says the
session allowance is gone, that is a fact about the account, not about the
code, and the old path recorded it as `implementation_failed`. The task then
spent an implementation attempt on something it could not have done
differently, and after three of those it was blocked -- with a finished
worktree nobody would look at again.

These tests pin the distinction and everything that hangs off it: the same
task, the same branch, the same worktree, the same lease, an untouched repair
budget, an approved fallback only, and Claude preferred again once the window
resets.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest import mock

from agentops_fixtures import REPO_ROOT, installed_harnesses

from services.agentops import (
    approvals,
    classify,
    coordinator,
    executors,
    leases,
    local,
    localstate,
    routing,
    state,
)

SESSION_LIMIT = "You have hit your session limit. Your limit will reset later."


def failed_run(text: str = "", **extra: Any) -> dict[str, Any]:
    """A run record shaped like the one `executors.run` returns.

    `text` goes on stderr, which is the harness's own error channel. That is
    deliberate: it is the channel the detector trusts, and a test that put the
    message where a model's prose lands would be asserting the behaviour this
    explicitly does not have.
    """
    record: dict[str, Any] = {
        "ok": False,
        "outcome": "failed",
        "run_id": "r1",
        "role": "implement",
        "model": "sonnet",
        "harness": "claude-cli",
        "provider": "anthropic",
        "returncode": 1,
        "turns": 1,
        "last_action": "",
        "stderr": text,
        "events": [],
    }
    record.update(extra)
    return record


def model_said(text: str, **extra: Any) -> dict[str, Any]:
    """A failed run where only the model's own output mentions something."""
    return failed_run("", last_action=text, **extra)


def assignment(lane: str) -> routing.Assignment:
    return routing.Assignment(
        lane=lane,
        model=f"{lane}/model",
        harness="claude-code-action",
        harness_model="sonnet" if lane == local.CLAUDE_LANE else "deepseek/x",
        effort="high",
        capability_class="STRONG_CODING",
        reason="test",
    )


CODEX_LIMIT = (
    "You've hit your usage limit. Upgrade to Pro "
    "(https://chatgpt.com/explore/pro), visit "
    "https://chatgpt.com/codex/settings/usage to purchase more credits "
    "or try again at 11:54 PM."
)

# The same refusal, dated. Codex prints it both ways and only the bare form
# was read, so this one fell back to the five-hour window.
CODEX_LIMIT_DATED = (
    "You've hit your usage limit. Upgrade to Pro "
    "(https://chatgpt.com/explore/pro), visit "
    "https://chatgpt.com/codex/settings/usage to purchase more credits "
    "or try again at Sep 21st, 2026 1:03 AM."
)


class TestTheResetTheHarnessNames(unittest.TestCase):
    """Codex says when it comes back. It is worth reading.

    This is the message the lane returned twice on 2026-09-19. The clock time
    was discarded for want of a date and a zone, the lane fell back to its
    declared five-hour window, and both wake-ups were refused in under ten
    seconds and re-cooled for another five hours.
    """

    def test_a_named_clock_time_becomes_the_reset(self) -> None:
        found = executors.exhaustion(failed_run(CODEX_LIMIT))
        assert found is not None
        reset = datetime.fromisoformat(found["reset_at"])
        self.assertEqual((reset.hour, reset.minute), (23, 54))
        self.assertIsNotNone(reset.tzinfo)

    def test_a_dated_reset_is_read_the_same_way(self) -> None:
        """Task 22's refusal, which the bare-clock pattern did not match.

        It fell back to the five-hour window and put the wake-up at 06:53Z
        when the lane was back at 06:03Z -- fifty minutes of a Codex-only task
        spent waiting for an allowance that had already returned.
        """
        found = executors.exhaustion(failed_run(CODEX_LIMIT_DATED))
        assert found is not None
        reset = datetime.fromisoformat(found["reset_at"])
        self.assertEqual((reset.hour, reset.minute), (1, 3))
        self.assertIsNotNone(reset.tzinfo)
        self.assertGreater(reset, datetime.now().astimezone())

    def test_a_time_already_past_today_means_tomorrow(self) -> None:
        """Never a reset in the past: that returns the lane to the pool at
        once, which is the failure this replaces rather than repeats."""
        found = executors.exhaustion(failed_run(CODEX_LIMIT))
        assert found is not None
        self.assertGreater(
            datetime.fromisoformat(found["reset_at"]), datetime.now().astimezone()
        )

    def test_a_machine_readable_timestamp_still_wins(self) -> None:
        run = failed_run(
            "usage limit reached; resets at 2026-09-20T08:00:00+00:00"
            " or try again at 11:54 PM"
        )
        found = executors.exhaustion(run)
        assert found is not None
        self.assertEqual(found["reset_at"], "2026-09-20T08:00:00+00:00")

    def test_an_allowance_message_with_no_time_still_has_no_reset(self) -> None:
        """Silence leaves the caller on the lane's declared window."""
        found = executors.exhaustion(failed_run("You've hit your usage limit."))
        assert found is not None
        self.assertEqual(found["reset_at"], "")

    def test_a_clock_time_without_an_allowance_message_is_not_exhaustion(self) -> None:
        self.assertIsNone(executors.exhaustion(failed_run("try again at 11:54 PM")))


class TestExhaustionIsRecognised(unittest.TestCase):
    """What counts as "the account ran out", and what deliberately does not."""

    def test_a_session_limit_on_the_error_channel_is_provider_exhaustion(self) -> None:
        found = executors.exhaustion(failed_run(SESSION_LIMIT))
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found["marker"], "session limit")

    def test_an_error_result_event_is_read_too(self) -> None:
        run = failed_run(
            "",
            events=[
                {
                    "type": "result",
                    "subtype": "error_during_execution",
                    "is_error": True,
                    "result": "Claude usage limit reached for this account",
                }
            ],
        )
        self.assertIsNotNone(executors.exhaustion(run))

    def test_the_models_own_output_is_never_trusted_for_this(self) -> None:
        """The task's own diff or test output may say anything at all.

        Reading it as an exhausted account would park a healthy provider and
        skip the repair the task actually needs, so only the harness's error
        channel counts.
        """
        self.assertIsNone(executors.exhaustion(model_said(SESSION_LIMIT)))
        self.assertIsNone(
            executors.exhaustion(
                model_said("I added a test for when the usage limit is exceeded")
            )
        )

    def test_a_successful_result_event_is_not_searched(self) -> None:
        run = failed_run(
            "",
            events=[
                {
                    "type": "result",
                    "subtype": "success",
                    "result": "documented the quota exceeded path",
                }
            ],
        )
        self.assertIsNone(executors.exhaustion(run))

    def test_a_failing_test_suite_is_not_provider_exhaustion(self) -> None:
        run = failed_run("3 tests failed: assert 1 == 2 in the backoff helper")
        self.assertIsNone(executors.exhaustion(run))

    def test_a_timeout_is_not_provider_exhaustion(self) -> None:
        run = failed_run("worker exceeded its wall clock", outcome="timeout")
        self.assertIsNone(executors.exhaustion(run))

    def test_a_successful_run_is_never_exhaustion(self) -> None:
        run = failed_run(SESSION_LIMIT, ok=True, outcome="completed")
        self.assertIsNone(executors.exhaustion(run))

    def test_an_explicit_iso_reset_instant_is_used(self) -> None:
        run = failed_run("Session limit reached. Resets at 2026-09-17T05:00:00Z")
        found = executors.exhaustion(run)
        assert found is not None
        self.assertEqual(found["reset_at"], "2026-09-17T05:00:00Z")

    def test_a_vague_reset_time_falls_back_to_the_window(self) -> None:
        """A bare "3pm" has no date and no zone; guessing one is worse."""
        found = executors.exhaustion(failed_run("session limit; resets at 3pm"))
        assert found is not None
        self.assertEqual(found["reset_at"], "")


class ClaudeFirstCase(unittest.TestCase):
    """A real repository, backlog and router. Only the harness is a fake."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "repo"
        (self.root / "ops" / "state").mkdir(parents=True)
        (self.root / "docs" / "projects").mkdir(parents=True)
        shutil.copy(
            REPO_ROOT / "ops" / "policy.json", self.root / "ops" / "policy.json"
        )
        shutil.copy(
            REPO_ROOT / "docs" / "06-tasks.md", self.root / "docs" / "06-tasks.md"
        )
        shutil.copy(
            REPO_ROOT / "docs" / "projects" / "README.md",
            self.root / "docs" / "projects" / "README.md",
        )
        for name in ("models.json", "providers.json", "budget.json", "progress.json"):
            shutil.copy(
                REPO_ROOT / "ops" / "state" / name, self.root / "ops" / "state" / name
            )
        (self.root / "ops" / "state" / "tasks.json").write_text(
            json.dumps({"leases": {}}), encoding="utf-8"
        )
        for args in (
            ("init", "-q"),
            ("config", "user.email", "t@example.com"),
            ("config", "user.name", "Test"),
            ("add", "-A"),
            ("commit", "-qm", "fixture"),
        ):
            subprocess.run(
                ["git", *args], cwd=str(self.root), check=False, capture_output=True
            )
        self.paths = localstate.ensure(localstate.LocalPaths(self.root))
        local.enable_local(self.paths, by="test")
        self.ctx = coordinator.load_context(self.root)
        self.ctx.tasks = local.load_leases(self.root, self.paths)
        candidate = coordinator.next_eligible(self.ctx)
        assert candidate is not None, "the fixture backlog has no eligible task"
        self.candidate = candidate
        self.store = approvals.load(self.paths)

    @contextlib.contextmanager
    def both_harnesses(self) -> Iterator[None]:
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-test-value"}):
            with installed_harnesses(claude=True, opencode=True):
                yield

    def approve_openrouter(self) -> str:
        inputs = self.ctx.routing_inputs()
        class_name = routing.capability_class(
            inputs.policy, classify.classify(self.candidate.task)
        )
        eligible = routing.eligible_models(inputs, class_name, "openrouter")
        self.assertTrue(eligible, f"no OpenRouter model meets {class_name}")
        chosen = eligible[0].id
        approvals.set_state(
            self.paths, self.store, chosen, approvals.APPROVED, risk_class="high"
        )
        return chosen

    def plan(self, provider: str = "claude-first", **kwargs: Any) -> Any:
        config = localstate.load_config(self.paths)
        config["provider"] = provider
        return local.local_plan(
            self.ctx, self.candidate, self.store, config=config, **kwargs
        )

    def attempt(
        self,
        runs: list[dict[str, Any]],
        *,
        provider: str = "claude-first",
        fallback: routing.Assignment | None = None,
        tasks: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Drive `implement_with_failover` with scripted harness results."""
        config = localstate.load_config(self.paths)
        config["provider"] = provider
        seen: list[Any] = []

        def fake_implement(*_args: Any, **kwargs: Any) -> dict[str, Any]:
            seen.append(kwargs["assignment"])
            return runs[min(len(seen) - 1, len(runs) - 1)]

        with mock.patch.object(local, "implement_once", fake_implement):
            result = local.implement_with_failover(
                self.root,
                self.paths,
                task_id=self.candidate.task.id,
                assignment=assignment(local.CLAUDE_LANE),
                worktree=self.root,
                config=config,
                policy=self.ctx.policy,
                prompt="do the task",
                role="implement",
                popen=None,
                tasks=tasks if tasks is not None else self.ctx.tasks,
                replan=lambda _excluded: fallback,
            )
        result["lanes_used"] = [item.lane for item in seen]
        return result


class TestClaudeIsPreferred(ClaudeFirstCase):
    def test_claude_first_is_an_accepted_provider(self) -> None:
        self.assertIn("claude-first", local.PROVIDERS)

    def test_a_healthy_claude_takes_the_work(self) -> None:
        with self.both_harnesses():
            self.approve_openrouter()
            plan = self.plan()
        self.assertIsNotNone(plan.writer, plan.blocked_reason)
        self.assertEqual(plan.writer.lane, local.CLAUDE_LANE)

    def test_claude_first_permits_the_fallback_lanes_as_well(self) -> None:
        """Claude first, but not Claude only -- and the set grew on 2026-09-18.

        The name is about preference, not exclusivity: it says which lane runs
        while its allowance lasts, not which lanes exist. Leaving the Codex
        subscription out would waste a whole included allowance and leave
        frontend work with no permitted writer at all.
        """
        self.assertEqual(
            local.provider_lanes({"provider": "claude-first"}),
            ("claude_subscription", "codex_local", "openrouter"),
        )
        # Claude is still what runs first.
        self.assertEqual(
            local.provider_lanes({"provider": "claude-first"})[0], local.CLAUDE_LANE
        )

    def test_the_status_names_every_permitted_lane(self) -> None:
        status = local.provider_status({"provider": "claude-first"})
        self.assertEqual(status["provider"], "claude-first")
        self.assertEqual(
            sorted(status["lanes"]),
            ["claude_subscription", "codex_local", "openrouter"],
        )


class TestCooldownMovesTheWork(ClaudeFirstCase):
    def test_an_exhausted_claude_is_excluded_and_openrouter_is_chosen(self) -> None:
        with self.both_harnesses():
            self.approve_openrouter()
            local.mark_lane_exhausted(
                self.paths, local.CLAUDE_LANE, policy=self.ctx.policy
            )
            local.merge_local_health(self.paths, self.ctx)
            plan = self.plan()
        self.assertIsNotNone(plan.writer, plan.blocked_reason)
        self.assertEqual(plan.writer.lane, "openrouter")

    def test_the_cooldown_is_local_and_never_dirties_the_tracked_ledger(self) -> None:
        tracked = self.root / "ops" / "state" / "providers.json"
        before = tracked.read_text(encoding="utf-8")
        local.mark_lane_exhausted(self.paths, local.CLAUDE_LANE, policy=self.ctx.policy)
        self.assertEqual(before, tracked.read_text(encoding="utf-8"))
        self.assertTrue(self.paths.providers.exists())

    def test_claude_is_preferred_again_once_the_window_resets(self) -> None:
        past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat(timespec="seconds")
        local.mark_lane_exhausted(
            self.paths, local.CLAUDE_LANE, policy=self.ctx.policy, reset_at=past
        )
        self.assertEqual(
            local.local_provider_health(self.paths)[local.CLAUDE_LANE], "AVAILABLE"
        )
        with self.both_harnesses():
            self.approve_openrouter()
            local.merge_local_health(self.paths, self.ctx)
            plan = self.plan()
        self.assertEqual(plan.writer.lane, local.CLAUDE_LANE)

    def test_a_live_cooldown_reports_when_it_returns(self) -> None:
        local.mark_lane_exhausted(self.paths, local.CLAUDE_LANE, policy=self.ctx.policy)
        cooling = local.provider_cooldowns(self.paths)
        self.assertIn(local.CLAUDE_LANE, cooling)
        self.assertTrue(cooling[local.CLAUDE_LANE])

    def test_the_default_window_is_used_when_no_reset_is_printed(self) -> None:
        recorded = local.mark_lane_exhausted(
            self.paths, local.CLAUDE_LANE, policy=self.ctx.policy
        )
        reset = datetime.fromisoformat(recorded["reset_at"])
        seconds = (reset - datetime.now(UTC)).total_seconds()
        self.assertGreater(seconds, local.DEFAULT_USAGE_WINDOW_SECONDS - 120)

    def test_merging_local_health_keeps_the_tracked_privacy_confirmation(self) -> None:
        """A cooldown must not knock another lane out for the wrong reason."""
        self.ctx.providers.setdefault("lanes", {}).setdefault("openrouter", {})[
            "privacy_confirmed"
        ] = True
        local.mark_lane_exhausted(self.paths, local.CLAUDE_LANE, policy=self.ctx.policy)
        local.merge_local_health(self.paths, self.ctx)
        self.assertTrue(self.ctx.providers["lanes"]["openrouter"]["privacy_confirmed"])


class TestTheTaskSurvivesTheFailover(ClaudeFirstCase):
    def test_a_session_limit_continues_the_same_task_on_openrouter(self) -> None:
        result = self.attempt(
            [failed_run(SESSION_LIMIT), failed_run("done", ok=True)],
            fallback=assignment("openrouter"),
        )
        self.assertEqual(result["blocked"], "")
        self.assertEqual(result["lanes_used"], [local.CLAUDE_LANE, "openrouter"])
        self.assertEqual(result["assignment"].lane, "openrouter")
        self.assertTrue(result["run"]["ok"])

    def test_the_failover_is_recorded_with_both_lanes(self) -> None:
        result = self.attempt(
            [failed_run(SESSION_LIMIT), failed_run("done", ok=True)],
            fallback=assignment("openrouter"),
        )
        self.assertEqual(len(result["failovers"]), 1)
        transition = result["failovers"][0]
        self.assertEqual(transition["previous_lane"], local.CLAUDE_LANE)
        self.assertEqual(transition["next_lane"], "openrouter")
        self.assertEqual(transition["reason"], "provider_exhausted")

    def test_exhaustion_puts_claude_into_cooldown(self) -> None:
        self.attempt(
            [failed_run(SESSION_LIMIT), failed_run("done", ok=True)],
            fallback=assignment("openrouter"),
        )
        self.assertEqual(
            local.local_provider_health(self.paths)[local.CLAUDE_LANE], "COOLDOWN"
        )

    def test_an_ordinary_failure_never_changes_lane(self) -> None:
        result = self.attempt(
            [failed_run("the tests do not pass")], fallback=assignment("openrouter")
        )
        self.assertEqual(result["lanes_used"], [local.CLAUDE_LANE])
        self.assertEqual(result["failovers"], [])
        self.assertEqual(
            local.local_provider_health(self.paths).get(local.CLAUDE_LANE, "AVAILABLE"),
            "AVAILABLE",
        )

    def test_no_approved_fallback_blocks_waiting_for_the_provider(self) -> None:
        result = self.attempt([failed_run(SESSION_LIMIT)], fallback=None)
        self.assertIn("BLOCKED_WAITING_PROVIDER", result["blocked"])

    def test_claude_only_mode_blocks_rather_than_reaching_for_openrouter(self) -> None:
        result = self.attempt(
            [failed_run(SESSION_LIMIT)],
            provider="claude",
            fallback=assignment("openrouter"),
        )
        self.assertIn("BLOCKED_WAITING_PROVIDER", result["blocked"])
        self.assertEqual(result["lanes_used"], [local.CLAUDE_LANE])

    def test_every_lane_exhausted_stops_instead_of_spinning(self) -> None:
        result = self.attempt(
            [failed_run(SESSION_LIMIT)], fallback=assignment("openrouter")
        )
        self.assertIn("BLOCKED_WAITING_PROVIDER", result["blocked"])
        self.assertLessEqual(len(result["failovers"]), local.MAX_PROVIDER_FAILOVERS)


class TestTheBudgetIsNotSpent(ClaudeFirstCase):
    def test_exhaustion_is_decided_before_the_outcome_ladder_sees_the_run(self) -> None:
        """`classify_outcome` is what charges the attempt ladder.

        It has no opinion about allowances and is not taught one; the failover
        path intercepts the run first, so an exhausted provider never reaches
        it and never becomes `implementation_failed`.
        """
        self.assertEqual(
            local.classify_outcome(failed_run(SESSION_LIMIT), None, []),
            "implementation_failed",
        )
        self.assertIsNotNone(executors.exhaustion(failed_run(SESSION_LIMIT)))

    def test_no_attempt_or_repair_cycle_is_spent_by_a_failover(self) -> None:
        tasks: dict[str, Any] = {"leases": {}}
        leases.acquire(
            tasks,
            self.ctx.policy,
            task_id=self.candidate.task.id,
            owner="test",
            branch="block-x-t1-fixture",
            assignment={"lane": local.CLAUDE_LANE},
            run_id="r1",
        )
        key = str(self.candidate.task.id)
        before = dict(tasks["leases"][key])

        self.attempt(
            [failed_run(SESSION_LIMIT), failed_run("done", ok=True)],
            fallback=assignment("openrouter"),
            tasks=tasks,
        )

        after = tasks["leases"][key]
        self.assertEqual(after.get("attempts"), before.get("attempts"))
        self.assertEqual(
            after.get("ci_repair_cycles", 0), before.get("ci_repair_cycles", 0)
        )
        self.assertEqual(
            after.get("review_repair_cycles", 0), before.get("review_repair_cycles", 0)
        )
        self.assertEqual(after.get("branch"), before.get("branch"))
        self.assertEqual(after.get("state"), before.get("state"))


class TestAParkedTaskComesBack(ClaudeFirstCase):
    """A provider stop must not be the end of the task.

    Releasing it as `blocked` was: `blocked` is where exhausted attempts go,
    the coordinator refuses a blocked lease until a human clears it, and the
    task's worktree was stranded for good. Waiting for an allowance to refill
    has to be a state the task returns from by itself.
    """

    def park(self) -> dict[str, Any]:
        tasks: dict[str, Any] = {"leases": {}}
        leases.acquire(
            tasks,
            self.ctx.policy,
            task_id=self.candidate.task.id,
            owner="test",
            branch="block-x-t1-fixture",
            assignment={"lane": local.CLAUDE_LANE},
            run_id="r1",
        )
        local._finish(
            self.paths,
            tasks,
            self.ctx.policy,
            self.candidate.task.id,
            local.WAITING_PROVIDER,
            once_key="r1",
        )
        return tasks

    def test_the_lease_is_parked_rather_than_blocked(self) -> None:
        tasks = self.park()
        lease = tasks["leases"][str(self.candidate.task.id)]
        self.assertEqual(lease["state"], leases.WAITING_PROVIDER)
        self.assertNotIn(lease["state"], leases.TERMINAL_STATES)
        self.assertNotIn(lease["state"], leases.ACTIVE_STATES)

    def test_the_unused_attempt_is_handed_back(self) -> None:
        tasks = self.park()
        self.assertEqual(tasks["leases"][str(self.candidate.task.id)]["attempts"], 0)

    def test_the_branch_and_assignment_survive_the_park(self) -> None:
        lease = self.park()["leases"][str(self.candidate.task.id)]
        self.assertEqual(lease["branch"], "block-x-t1-fixture")
        self.assertEqual(lease["assignment"]["lane"], local.CLAUDE_LANE)

    def test_the_coordinator_will_offer_the_task_again(self) -> None:
        self.ctx.tasks = self.park()
        again = coordinator.evaluate(self.ctx, self.candidate.task)
        self.assertTrue(again.eligible, again.reasons)

    def test_a_parked_task_is_still_dispatchable_locally(self) -> None:
        self.assertEqual(local.settled_locally(self.park(), self.candidate.task.id), "")

    def test_a_genuinely_blocked_task_is_still_refused(self) -> None:
        """The park path must not soften the real one."""
        tasks: dict[str, Any] = {"leases": {}}
        leases.acquire(
            tasks,
            self.ctx.policy,
            task_id=self.candidate.task.id,
            owner="test",
            branch="b",
            assignment={"lane": local.CLAUDE_LANE},
            run_id="r1",
        )
        leases.release(tasks, self.candidate.task.id, "blocked")
        self.ctx.tasks = tasks
        again = coordinator.evaluate(self.ctx, self.candidate.task)
        self.assertFalse(again.eligible)


class TestOnlyApprovedFallbacksRun(ClaudeFirstCase):
    def test_an_unapproved_openrouter_model_cannot_take_the_task(self) -> None:
        with self.both_harnesses():
            local.mark_lane_exhausted(
                self.paths, local.CLAUDE_LANE, policy=self.ctx.policy
            )
            local.merge_local_health(self.paths, self.ctx)
            plan = self.plan()
        self.assertIsNone(plan.writer)
        self.assertIn("BLOCKED_PROVIDER", str(plan.blocked_reason))

    def test_an_uninstalled_fallback_harness_cannot_take_the_task(self) -> None:
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-test-value"}):
            with installed_harnesses(claude=True, opencode=False):
                self.approve_openrouter()
                local.mark_lane_exhausted(
                    self.paths, local.CLAUDE_LANE, policy=self.ctx.policy
                )
                local.merge_local_health(self.paths, self.ctx)
                plan = self.plan()
        self.assertIsNone(plan.writer)


class TestTheSwitchDoesNotTouchGovernance(ClaudeFirstCase):
    def test_cloud_autonomy_stays_off_and_the_cap_is_not_rewritten(self) -> None:
        """Recording a local cooldown must not edit governance at all.

        The cap is read rather than asserted to be a particular number: what
        this test is about is that a local event does not write to the tracked
        policy, not what the owner has set the cap to.
        """
        before = state.load_policy(state.Paths(self.root))["autonomy"]
        local.mark_lane_exhausted(self.paths, local.CLAUDE_LANE, policy=self.ctx.policy)
        policy = state.load_policy(state.Paths(self.root))
        self.assertFalse(policy["autonomy"]["enabled"])
        self.assertEqual(policy["autonomy"], before)


if __name__ == "__main__":
    unittest.main()
