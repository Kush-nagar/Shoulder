"""Leases, interruption recovery, bounded retries, and the kill switch."""

from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest import mock

from agentops_fixtures import REPO_ROOT, make_stale, policy

from services.agentops import coordinator, leases, state


def ago(seconds: int) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat(
        timespec="seconds"
    )


def assignment() -> dict[str, Any]:
    return {"lane": "claude_subscription", "model": "anthropic/claude-sonnet-5"}


class TestLeaseExclusivity(unittest.TestCase):
    """41. One writer per task, per branch, per checkout."""

    def setUp(self) -> None:
        self.policy = policy()
        self.tasks: dict[str, Any] = {"leases": {}}

    def _acquire(self, owner: str, task_id: int = 14) -> dict[str, Any]:
        return leases.acquire(
            self.tasks,
            self.policy,
            task_id=task_id,
            owner=owner,
            branch=f"block-04-t{task_id}",
            assignment=assignment(),
        )

    def test_first_worker_acquires_the_lease(self) -> None:
        lease = self._acquire("worker-a")
        self.assertEqual(lease["owner"], "worker-a")
        self.assertEqual(lease["state"], "assigned")
        self.assertEqual(lease["attempts"], 1)

    def test_second_worker_is_refused(self) -> None:
        self._acquire("worker-a")
        with self.assertRaises(leases.LeaseConflict) as raised:
            self._acquire("worker-b")
        self.assertIn("worker-a", str(raised.exception))

    def test_parallel_writer_limit_is_enforced(self) -> None:
        """52. Concurrency never exceeds the configured ceiling.

        The ceiling is whatever policy says -- it was 1 until 2026-09-19 and is
        3 now -- so the test fills it rather than naming it. Pinning the number
        here would make raising the cap look like a broken invariant instead of
        the deliberate edit it is, and would stop testing the thing that
        matters: that the writer after the last permitted one is refused.
        """
        cap = int(self.policy["autonomy"]["max_parallel_writers"])
        for index in range(cap):
            self._acquire(f"worker-{index}", task_id=14 + index)
        with self.assertRaises(leases.LeaseConflict) as raised:
            self._acquire("worker-over", task_id=14 + cap)
        self.assertIn("max_parallel_writers", str(raised.exception))

    def test_raising_the_limit_allows_another_writer(self) -> None:
        cap = int(self.policy["autonomy"]["max_parallel_writers"])
        self.policy["autonomy"]["max_parallel_writers"] = cap + 1
        for index in range(cap):
            self._acquire(f"worker-{index}", task_id=14 + index)
        extra = self._acquire("worker-extra", task_id=14 + cap)
        self.assertEqual(extra["owner"], "worker-extra")

    def test_released_lease_frees_the_task(self) -> None:
        self._acquire("worker-a")
        leases.release(self.tasks, 14, "merged")
        replacement = self._acquire("worker-b")
        self.assertEqual(replacement["owner"], "worker-b")

    def test_release_rejects_a_non_terminal_state(self) -> None:
        self._acquire("worker-a")
        with self.assertRaises(ValueError):
            leases.release(self.tasks, 14, "implementing")


class TestHeartbeatAndStaleness(unittest.TestCase):
    """42-43. A live worker keeps its branch; a dead one gives it up."""

    def setUp(self) -> None:
        self.policy = policy()
        self.tasks: dict[str, Any] = {"leases": {}}
        leases.acquire(
            self.tasks,
            self.policy,
            task_id=14,
            owner="worker-a",
            branch="b",
            assignment=assignment(),
        )

    def test_heartbeat_advances_the_clock(self) -> None:
        self.tasks["leases"]["14"]["heartbeat_at"] = ago(600)
        lease = leases.heartbeat(self.tasks, 14, "worker-a")
        self.assertFalse(leases.is_stale(lease, self.policy))

    def test_heartbeat_from_a_stranger_is_refused(self) -> None:
        with self.assertRaises(leases.LeaseConflict):
            leases.heartbeat(self.tasks, 14, "worker-b")

    def test_a_heartbeating_worker_is_not_stale_past_nominal_expiry(self) -> None:
        """A live worker running long must not have its branch taken away."""
        lease = self.tasks["leases"]["14"]
        lease["expires_at"] = ago(60)
        lease["heartbeat_at"] = ago(5)
        self.assertFalse(leases.is_stale(lease, self.policy))

    def test_a_silent_worker_becomes_stale(self) -> None:
        lease = make_stale(self.tasks["leases"]["14"], self.policy)
        self.assertTrue(leases.is_stale(lease, self.policy))

    def test_stale_lease_is_recovered_and_the_takeover_is_recorded(self) -> None:
        make_stale(self.tasks["leases"]["14"], self.policy)
        recovered = leases.acquire(
            self.tasks,
            self.policy,
            task_id=14,
            owner="worker-b",
            branch="b",
            assignment=assignment(),
        )
        self.assertEqual(recovered["owner"], "worker-b")
        self.assertEqual(recovered["attempts"], 2)
        self.assertEqual(recovered["recovered_from"][0]["owner"], "worker-a")

    def test_active_leases_exclude_stale_ones(self) -> None:
        make_stale(self.tasks["leases"]["14"], self.policy)
        self.assertEqual(leases.active_leases(self.tasks, self.policy), [])

    def test_a_lease_with_no_timestamps_is_stale(self) -> None:
        self.assertTrue(leases.is_stale({"state": "implementing"}, self.policy))


class TestCheckpointRecovery(unittest.TestCase):
    """45-47. A replacement worker continues from state, not from a transcript."""

    def setUp(self) -> None:
        self.policy = policy()
        self.tasks: dict[str, Any] = {"leases": {}}
        leases.acquire(
            self.tasks,
            self.policy,
            task_id=14,
            owner="worker-a",
            branch="block-04-t14",
            assignment=assignment(),
        )

    def test_checkpoint_records_everything_a_successor_needs(self) -> None:
        leases.checkpoint(
            self.tasks,
            14,
            "worker-a",
            state="implementing",
            commit="abc1234",
            complete=["migration 0007", "observation model"],
            remaining=["marking UI", "Playwright flow"],
            tests={"python": "41 passed"},
            next_action="write the keyboard handler",
        )
        saved = self.tasks["leases"]["14"]["checkpoint"]
        self.assertEqual(saved["commit"], "abc1234")
        self.assertEqual(saved["remaining"], ["marking UI", "Playwright flow"])
        self.assertEqual(saved["next_action"], "write the keyboard handler")

    def test_interrupted_worker_is_replaced_without_losing_progress(self) -> None:
        """Simulate a crash: checkpoint, go silent, let a new worker take over."""
        leases.checkpoint(
            self.tasks,
            14,
            "worker-a",
            state="implementing",
            commit="abc1234",
            complete=["migration 0007"],
            remaining=["marking UI"],
        )
        make_stale(self.tasks["leases"]["14"], self.policy)

        successor = leases.acquire(
            self.tasks,
            self.policy,
            task_id=14,
            owner="worker-b",
            branch="block-04-t14",
            assignment=assignment(),
        )
        self.assertEqual(successor["owner"], "worker-b")
        self.assertEqual(successor["branch"], "block-04-t14")
        self.assertEqual(successor["checkpoint"]["commit"], "abc1234")
        self.assertEqual(successor["checkpoint"]["remaining"], ["marking UI"])

    def test_checkpoint_requires_the_lease_owner(self) -> None:
        with self.assertRaises(leases.LeaseConflict):
            leases.checkpoint(self.tasks, 14, "worker-b", state="implementing")

    def test_attempts_are_bounded_by_policy(self) -> None:
        """48-50. Retries are finite; the ceiling is configured, not implicit."""
        limits = self.policy["escalation"]
        for key in (
            "max_implementation_attempts",
            "max_ci_repair_cycles",
            "max_review_repair_cycles",
        ):
            self.assertGreaterEqual(limits[key], 1)
            self.assertLessEqual(limits[key], 5)

    def test_attempt_count_survives_recovery(self) -> None:
        for expected in (2, 3):
            make_stale(self.tasks["leases"]["14"], self.policy)
            lease = leases.acquire(
                self.tasks,
                self.policy,
                task_id=14,
                owner=f"worker-{expected}",
                branch="b",
                assignment=assignment(),
            )
            self.assertEqual(lease["attempts"], expected)


class TestKillSwitch(unittest.TestCase):
    """51/61. Autonomy off means no feature work is assigned."""

    def test_policy_default_is_off(self) -> None:
        self.assertFalse(state.autonomy_enabled(policy()))

    def test_environment_variable_can_disable_without_a_commit(self) -> None:
        import os

        paths = state.Paths(REPO_ROOT)
        previous = os.environ.get("AUTONOMY_ENABLED")
        try:
            os.environ["AUTONOMY_ENABLED"] = "true"
            self.assertTrue(state.autonomy_enabled(state.load_policy(paths)))
            os.environ["AUTONOMY_ENABLED"] = "false"
            self.assertFalse(state.autonomy_enabled(state.load_policy(paths)))
        finally:
            if previous is None:
                os.environ.pop("AUTONOMY_ENABLED", None)
            else:
                os.environ["AUTONOMY_ENABLED"] = previous

    def test_dry_run_reports_autonomy_state_without_acting(self) -> None:
        result = coordinator.dry_run(REPO_ROOT)
        self.assertFalse(result["autonomy_enabled"])
        self.assertEqual(result.get("active_leases"), [])

    def test_dispatch_refuses_while_autonomy_is_off(self) -> None:
        from services.agentops import cli

        before = coordinator.load_context(REPO_ROOT).tasks.get("leases", {})
        code = cli.main(["--root", str(REPO_ROOT), "dispatch"])
        self.assertEqual(code, 0)
        after = coordinator.load_context(REPO_ROOT).tasks.get("leases", {})
        self.assertEqual(after, before, "disabled dispatch must not mutate leases")


class TestStateWriting(unittest.TestCase):
    """State is rewritten on every run; it must stay gate-clean."""

    def test_state_is_written_with_lf_endings_on_every_platform(self) -> None:
        """Default text mode emits CRLF on Windows, which the formatter rejects.

        A coordinator run on a workstation would otherwise break the quality
        gate it exists to protect.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "sample.json"
            state.write_json(target, {"leases": {}, "note": "two\nlines"})
            raw = target.read_bytes()
            self.assertNotIn(b"\r\n", raw)
            self.assertTrue(raw.endswith(b"\n"))

    def test_committed_state_files_use_lf(self) -> None:
        paths = state.Paths(REPO_ROOT)
        for path in (
            paths.progress,
            paths.providers,
            paths.tasks,
            paths.budget,
            paths.models,
        ):
            with self.subTest(path.name):
                self.assertNotIn(b"\r\n", path.read_bytes())

    def test_a_write_round_trip_is_stable(self) -> None:
        """Rewriting unchanged state must not produce a diff."""
        import tempfile

        payload = {"b": 2, "a": {"nested": [1, 2]}}
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "sample.json"
            state.write_json(target, payload)
            first = target.read_bytes()
            state.write_json(target, state.read_json(target))
            self.assertEqual(first, target.read_bytes())


class TestSeededStateShape(unittest.TestCase):
    """The committed state files must stay loadable and honest."""

    def setUp(self) -> None:
        self.ctx = coordinator.load_context(REPO_ROOT)

    def test_committed_leases_are_well_formed(self) -> None:
        committed = self.ctx.tasks.get("leases")
        if not isinstance(committed, dict):
            self.fail("committed task state must contain a lease table")
        completed = state.completed_tasks(self.ctx.progress)
        valid_states = (*leases.ACTIVE_STATES, *leases.TERMINAL_STATES)

        for key, lease in committed.items():
            with self.subTest(key):
                self.assertIsInstance(lease, dict)
                task_id = lease.get("task_id")
                self.assertIsInstance(task_id, int)
                self.assertEqual(key, str(task_id))
                self.assertIn(task_id, self.ctx.backlog.tasks)
                self.assertIsInstance(lease.get("branch"), str)
                self.assertTrue(lease["branch"])
                self.assertIn(lease.get("state"), valid_states)
                if lease["state"] in leases.ACTIVE_STATES:
                    self.assertNotIn(task_id, completed)

    def test_committed_spend_is_real_and_far_under_the_ceilings(self) -> None:
        """Qualification runs really do spend, and it is recorded.

        The ledger started empty; cloud verification then charged a fraction of
        a cent for real probe calls. What matters is that every recorded amount
        is finite, non-negative, and nowhere near a ceiling.
        """
        import math

        limits = self.ctx.policy["budget"]
        for bucket in ("daily", "monthly"):
            for period in self.ctx.budget.get("spend", {}).get(bucket, {}).values():
                for lane, amount in period.items():
                    with self.subTest(f"{bucket}:{lane}"):
                        self.assertTrue(math.isfinite(float(amount)))
                        self.assertGreaterEqual(float(amount), 0.0)
                        self.assertLess(
                            float(amount), float(limits["openrouter_daily_usd"])
                        )

    def test_no_lane_is_budget_blocked_at_rest(self) -> None:
        self.assertEqual(
            state.budget_blocked(self.ctx.policy, self.ctx.budget), frozenset()
        )

    def test_real_use_gate_is_closed(self) -> None:
        self.assertFalse(state.gate_passed(self.ctx.progress))

    def test_state_files_contain_no_secret_material(self) -> None:
        from services.agentops import notify

        for path in (
            self.ctx.paths.policy,
            self.ctx.paths.progress,
            self.ctx.paths.providers,
            self.ctx.paths.tasks,
            self.ctx.paths.budget,
        ):
            text = path.read_text(encoding="utf-8")
            for pattern in notify.CREDENTIAL_PATTERNS:
                self.assertIsNone(
                    pattern.search(text),
                    f"{path.name} looks like it holds a real credential",
                )


if __name__ == "__main__":
    unittest.main()


class TestSecondReviewFindings(unittest.TestCase):
    """Regressions for the defects the second review round found."""

    def setUp(self) -> None:
        self.policy = policy()
        self.tasks: dict[str, Any] = {"leases": {}}

    def test_a_long_running_worker_is_not_declared_stale(self) -> None:
        """A harness step can run for the whole job and cannot heartbeat.

        Treating a missed heartbeat alone as death would hand a live worker's
        branch to a second writer after 15 minutes.
        """
        lease = leases.acquire(
            self.tasks,
            self.policy,
            task_id=14,
            owner="worker-a",
            branch="block-04-t14",
            assignment=assignment(),
        )
        # Sixty minutes of silence, still inside the ninety-minute lease.
        lease["heartbeat_at"] = ago(3600)
        self.assertFalse(leases.is_stale(lease, self.policy))
        self.assertEqual(len(leases.active_leases(self.tasks, self.policy)), 1)

    def test_a_lease_goes_stale_after_expiry_plus_grace(self) -> None:
        lease = leases.acquire(
            self.tasks,
            self.policy,
            task_id=14,
            owner="worker-a",
            branch="block-04-t14",
            assignment=assignment(),
        )
        duration = int(self.policy["lease"]["duration_seconds"])
        grace = (
            self.policy["lease"]["heartbeat_seconds"]
            * self.policy["lease"]["stale_after_missed_heartbeats"]
        )
        lease["acquired_at"] = ago(duration + grace + 120)
        lease["heartbeat_at"] = ago(duration + grace + 120)
        lease["expires_at"] = ago(grace + 120)
        self.assertTrue(leases.is_stale(lease, self.policy))

    def test_the_coordinator_run_alone_never_proves_a_worker_finished(self) -> None:
        """`run_id` is the coordinator's, and it ends in seconds.

        Checking it would say the owner had finished while the worker it
        dispatched was still going, and the branch would be taken away.
        """
        from services.agentops import watchdog

        self.assertTrue(watchdog.owner_finished({"run_id": "123"}))

    def test_attaching_a_worker_makes_liveness_checkable(self) -> None:
        tasks: dict[str, Any] = {"leases": {}}
        leases.acquire(
            tasks,
            self.policy,
            task_id=14,
            owner="coordinator",
            branch="block-04-t14",
            assignment=assignment(),
            run_id="coordinator-run",
        )
        lease = leases.attach_worker(tasks, 14, run_id="worker-run")
        self.assertEqual(lease["worker_run_id"], "worker-run")
        self.assertEqual(lease["run_id"], "coordinator-run")

    def test_codex_work_records_its_pull_request(self) -> None:
        tasks: dict[str, Any] = {"leases": {}}
        leases.acquire(
            tasks,
            self.policy,
            task_id=14,
            owner="coordinator",
            branch="block-04-t14",
            assignment=assignment(),
        )
        lease = leases.attach_worker(tasks, 14, pull_request=42)
        self.assertEqual(lease["pull_request"], 42)

    def test_the_lease_records_which_run_owns_it(self) -> None:
        """The watchdog proves the owner is gone rather than assuming."""
        lease = leases.acquire(
            self.tasks,
            self.policy,
            task_id=14,
            owner="run-123",
            branch="block-04-t14",
            assignment=assignment(),
            run_id="123",
        )
        self.assertEqual(lease["run_id"], "123")

    def test_a_still_running_owner_is_never_reclaimed(self) -> None:
        from unittest import mock

        from services.agentops import watchdog

        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(
                returncode=0, stdout='{"status":"in_progress"}'
            )
            self.assertFalse(watchdog.owner_finished({"worker_run_id": "123"}))
            run.return_value = mock.Mock(returncode=0, stdout='{"status":"completed"}')
            self.assertTrue(watchdog.owner_finished({"worker_run_id": "123"}))

    def test_an_unanswerable_liveness_query_holds_the_lease(self) -> None:
        """Fail closed.

        An API outage or rate limit must not let the sweep take a branch from a
        worker that is still running: two writers on one branch is worse than
        recovery arriving late.
        """
        from unittest import mock

        from services.agentops import watchdog

        # Nothing attached means nothing could still be running.
        self.assertTrue(watchdog.owner_finished({}))
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=1, stdout="")
            self.assertFalse(
                watchdog.owner_finished(
                    {"worker_run_id": "123", "heartbeat_at": ago(60)},
                    policy=self.policy,
                )
            )

    def test_a_long_unanswerable_lease_is_eventually_released(self) -> None:
        """Holding forever is its own failure.

        A lease pointing at a run that no longer exists would never be
        answerable, so after a long multiple of the grace window it is let go.
        """
        from unittest import mock

        from services.agentops import watchdog

        settings = self.policy["lease"]
        window = (
            settings["heartbeat_seconds"]
            * settings["stale_after_missed_heartbeats"]
            * watchdog.UNRESOLVED_GRACE_MULTIPLE
        )
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=1, stdout="")
            self.assertTrue(
                watchdog.owner_finished(
                    {"worker_run_id": "123", "heartbeat_at": ago(window + 600)},
                    policy=self.policy,
                )
            )

    def test_attempts_are_actually_bounded(self) -> None:
        """The policy promised a retry ceiling; nothing enforced it."""
        limit = int(self.policy["escalation"]["max_implementation_attempts"])
        for _ in range(limit):
            leases.acquire(
                self.tasks,
                self.policy,
                task_id=14,
                owner="worker",
                branch="block-04-t14",
                assignment=assignment(),
            )
            leases.release(self.tasks, 14, "abandoned")
        with self.assertRaises(leases.AttemptsExhausted):
            leases.acquire(
                self.tasks,
                self.policy,
                task_id=14,
                owner="worker",
                branch="block-04-t14",
                assignment=assignment(),
            )

    def test_spend_rejects_values_that_would_disable_the_ceiling(self) -> None:
        for bad in (-1.0, float("nan"), float("inf"), float("-inf")):
            with self.subTest(bad):
                with self.assertRaises(ValueError):
                    state.record_spend({}, "openrouter", bad, task_id=14)

    def test_spend_accepts_an_ordinary_amount(self) -> None:
        budget = state.record_spend({}, "openrouter", 0.25, task_id=14)
        self.assertEqual(state.task_spend(budget, 14), 0.25)


class TestEndToEndFailover(unittest.TestCase):
    """Failover driven through the real coordinator and real state files.

    The routing tests cover the decision in isolation. This covers the whole
    path: committed policy, a state file on disk, the coordinator loading it,
    and the plan actually changing when a lane goes into cooldown.
    """

    def setUp(self) -> None:
        import shutil
        import tempfile

        from agentops_fixtures import REPO_ROOT as root

        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        for relative in ("ops", "docs", "services"):
            shutil.copytree(root / relative, self.root / relative)
        self.addCleanup(shutil.rmtree, self.tmp, True)

        # Make every lane usable so the only variable is health.
        providers = state.read_json(state.Paths(self.root).providers)
        for lane in (
            "claude_subscription",
            "openrouter",
            "codex_cloud",
            "codex_local",
        ):
            state.mark_provider(providers, lane, "AVAILABLE", reason="test")
        for lane in ("codex_cloud", "codex_local"):
            state.mark_lane_qualified(providers, lane, evidence="test")
        # A lane whose privacy is enforced on the provider account stays
        # ineligible until the owner confirms it; this fixture is a fully
        # configured deployment.
        providers["lanes"]["openrouter"]["privacy_confirmed"] = True
        state.write_json(state.Paths(self.root).providers, providers)

        models = state.read_json(state.Paths(self.root).models)
        for record in models.get("models", {}).values():
            if not record.get("absent") and not record.get("deprecated"):
                record["qualification"] = "QUALIFIED"
        state.write_json(state.Paths(self.root).models, models)

    def plan_for(self, task_id: int) -> coordinator.Plan:
        ctx = coordinator.load_context(self.root)
        task = ctx.backlog.tasks[task_id]
        return coordinator.plan(ctx, coordinator.evaluate(ctx, task))

    def cool(self, lane: str) -> None:
        from datetime import UTC, datetime, timedelta

        paths = state.Paths(self.root)
        providers = state.read_json(paths.providers)
        state.mark_provider(
            providers,
            lane,
            "COOLDOWN",
            reason="allowance exhausted",
            reset_at=(datetime.now(UTC) + timedelta(hours=5)).isoformat(
                timespec="seconds"
            ),
        )
        state.write_json(paths.providers, providers)

    def test_a_backend_task_routes_before_any_failure(self) -> None:
        """Task 15 carries a security and migration risk, so it starts at Codex.

        The classifier raises it to CRITICAL on those risks alone, which is the
        class the owner sends to Codex at the top of the effort ladder. An
        ordinary backend task still starts at Claude; that is asserted in the
        routing tests, against a classification rather than this one task.
        """
        built = self.plan_for(15)
        assert built.writer is not None, built.blocked_reason
        self.assertEqual(built.writer.lane, "codex_local")
        self.assertEqual(built.writer.effort, "xhigh")

    def test_ordinary_backend_work_overflows_to_deepseek(self) -> None:
        """Owner decision, 2026-09-18: DeepSeek is Claude's overflow.

        This inverts what was asserted here before, and the reason is which
        resource is actually scarce. The older reading counted dollars, so an
        included Codex allowance beat metered credits. But Codex is not spare
        capacity any more: it is the only lane allowed to write frontend, and
        the one that takes every security, RLS and migration task. Spending it
        on an ordinary endpoint that DeepSeek can write for a fraction of a
        cent is what leaves the expensive work with nowhere to go.

        The restriction that matters is unchanged and asserted below: work
        DeepSeek may not write never lands here.
        """
        self.cool("claude_subscription")
        self.cool("codex_local")
        self.cool("codex_cloud")
        built = self.plan_for(15)
        assert built.writer is not None, built.blocked_reason
        self.assertEqual(built.writer.lane, "openrouter")

    def test_backend_work_reaches_codex_once_deepseek_is_cool_too(self) -> None:
        self.cool("claude_subscription")
        self.cool("openrouter")
        built = self.plan_for(15)
        assert built.writer is not None, built.blocked_reason
        lanes = state.read_json(state.Paths(self.root).policy)["lanes"]
        self.assertEqual(lanes[built.writer.lane]["provider"], "openai")

    def test_frontend_work_waits_when_every_permitted_lane_cools(self) -> None:
        """It must not fall through to a writer the policy forbids.

        Every lane allowed to write UI is cooled here -- since 2026-09-18 that
        is both Codex lanes, Claude having handed frontend back. The OpenRouter
        lane is still forbidden, and that is what must not be promoted.
        """
        self.cool("codex_cloud")
        self.cool("codex_local")
        self.cool("claude_subscription")
        built = self.plan_for(18)
        self.assertIsNone(built.writer)
        self.assertIn("BLOCKED_PROVIDER", built.blocked_reason or "")
        self.assertFalse(
            any("deepseek" in r.lower() for r in built.rejections if "forbids" not in r)
        )

    def test_codex_returns_to_the_pool_after_its_window(self) -> None:
        paths = state.Paths(self.root)
        providers = state.read_json(paths.providers)
        state.mark_provider(
            providers,
            "codex_cloud",
            "COOLDOWN",
            reason="allowance exhausted",
            reset_at="2000-01-01T00:00:00+00:00",
        )
        state.write_json(paths.providers, providers)

        # The other lanes are cooled so the recovered one is under test.
        self.cool("claude_subscription")
        self.cool("codex_local")
        built = self.plan_for(18)
        assert built.writer is not None, built.blocked_reason
        self.assertEqual(built.writer.lane, "codex_cloud")

    def test_everything_down_blocks_rather_than_improvising(self) -> None:
        # Every lane in policy, not a list written out here. A lane added later
        # is covered the day it is added; a hand-written roster would have gone
        # on passing while the new lane quietly took the work.
        for lane in state.read_json(state.Paths(self.root).policy)["lanes"]:
            self.cool(lane)
        built = self.plan_for(15)
        self.assertIsNone(built.writer)
        self.assertIn("BLOCKED_PROVIDER", built.blocked_reason or "")


class TestFourthReviewFindings(unittest.TestCase):
    """Regressions for the fourth review round."""

    def setUp(self) -> None:
        self.policy = policy()
        self.tasks: dict[str, Any] = {"leases": {}}

    def test_acquire_refuses_a_stale_lease_whose_owner_still_runs(self) -> None:
        """Timestamps are not proof.

        A worker queued longer than the grace window looks stale while being
        entirely alive, and reassigning it puts a second writer on its branch.
        Only the watchdog asked; acquisition did not.
        """
        from agentops_fixtures import make_stale

        leases.acquire(
            self.tasks,
            self.policy,
            task_id=14,
            owner="worker-a",
            branch="block-04-t14",
            assignment=assignment(),
        )
        make_stale(self.tasks["leases"]["14"], self.policy)

        with self.assertRaises(leases.LeaseConflict) as raised:
            leases.acquire(
                self.tasks,
                self.policy,
                task_id=14,
                owner="worker-b",
                branch="block-04-t14",
                assignment=assignment(),
                owner_finished=lambda _lease: False,
            )
        self.assertIn("still running", str(raised.exception))

    def test_acquire_proceeds_once_the_owner_has_stopped(self) -> None:
        from agentops_fixtures import make_stale

        leases.acquire(
            self.tasks,
            self.policy,
            task_id=14,
            owner="worker-a",
            branch="block-04-t14",
            assignment=assignment(),
        )
        make_stale(self.tasks["leases"]["14"], self.policy)
        lease = leases.acquire(
            self.tasks,
            self.policy,
            task_id=14,
            owner="worker-b",
            branch="block-04-t14",
            assignment=assignment(),
            owner_finished=lambda _lease: True,
        )
        self.assertEqual(lease["owner"], "worker-b")

    def test_a_worker_resumes_a_pushed_branch_rather_than_resetting_it(
        self,
    ) -> None:
        """`-B` with no start point would discard the previous attempt's work,
        and the later force-push would make that permanent."""
        from agentops_fixtures import REPO_ROOT as root

        text = (root / ".github/workflows/agentops-worker.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn('git checkout -B "$BRANCH" "origin/$BRANCH"', text)
        self.assertIn("git ls-remote --exit-code origin", text)

    def test_the_hand_off_write_cannot_ride_the_task_branch(self) -> None:
        """Delegation leaves the checkout on the task branch.

        Pushing HEAD from there used to be able to put that branch's starter
        commit on main, and reconcile would then read the task as already
        merged. The elaborate branch-switching that guarded against it is gone,
        because the hazard is gone: the state commit's tree is built from
        ops/state alone and HEAD is never pushed anywhere.
        """
        from agentops_fixtures import REPO_ROOT as root

        from services.agentops import statebranch

        text = (root / ".github/workflows/agentops-coordinator.yml").read_text(
            encoding="utf-8"
        )
        handoff = text.split("Record what the hand-off left behind", 1)[1]
        self.assertIn("cli state-push", handoff)
        self.assertNotIn("git push", handoff)
        self.assertNotIn("git checkout", handoff)

        # The tree is built from an empty index plus one directory, so nothing
        # else in the worktree can reach it.
        source = Path(statebranch.__file__).read_text(encoding="utf-8")
        self.assertIn('"read-tree", "--empty"', source)
        self.assertIn('"add", "--all", "--", TRACKED', source)


class TestSixthReviewFindings(unittest.TestCase):
    """Regressions for the sixth review round."""

    def setUp(self) -> None:
        self.policy = policy()

    def test_the_guard_accepts_the_worker_it_was_dispatched_for(self) -> None:
        """The coordinator takes the lease before the worker runs.

        Treating that lease as a conflict refused every legitimate worker, so
        nothing would ever have been implemented.
        """
        import shutil
        import tempfile

        from agentops_fixtures import REPO_ROOT as source

        tmp = tempfile.mkdtemp()
        root = Path(tmp)
        self.addCleanup(shutil.rmtree, tmp, True)
        for relative in ("ops", "docs", "services"):
            shutil.copytree(source / relative, root / relative)

        ctx = coordinator.load_context(root)
        # Whatever is genuinely next, rather than a pinned number: pinning one
        # meant finishing that task failed this check.
        pending = coordinator.next_eligible(ctx)
        assert pending is not None
        leases.acquire(
            ctx.tasks,
            ctx.policy,
            task_id=pending.task.id,
            owner="run-1",
            branch=coordinator.branch_name(pending.task, pending.block),
            assignment={"lane": "codex_cloud"},
        )
        state.write_json(ctx.paths.tasks, ctx.tasks)

        fresh = coordinator.load_context(root)
        task = fresh.backlog.tasks[pending.task.id]
        self.assertTrue(
            coordinator.evaluate(fresh, task, ignore_own_lease=True).eligible
        )
        self.assertFalse(coordinator.evaluate(fresh, task).eligible)

    def test_an_open_pull_request_outlives_its_finished_run(self) -> None:
        """A worker's run ending does not mean the work is done."""
        from unittest import mock

        from services.agentops import watchdog

        lease = {
            "worker_run_id": "123",
            "pull_request": 42,
            "heartbeat_at": state.now(),
        }
        with mock.patch.object(watchdog, "_run_finished", return_value=True):
            with mock.patch.object(
                watchdog, "_pull_request_finished", return_value=False
            ):
                self.assertFalse(watchdog.owner_finished(lease, policy=self.policy))
            with mock.patch.object(
                watchdog, "_pull_request_finished", return_value=True
            ):
                self.assertTrue(watchdog.owner_finished(lease, policy=self.policy))

    def test_a_pull_request_lease_is_never_released_on_a_timer(self) -> None:
        """Releasing because a query keeps failing is guessing work stopped.

        The pull request still exists and can be asked about again, so a longer
        fuse is the same failure, later.
        """
        from unittest import mock

        from services.agentops import watchdog

        settings = self.policy["lease"]
        grace = (
            settings["heartbeat_seconds"] * settings["stale_after_missed_heartbeats"]
        )
        very_old = ago(grace * watchdog.UNRESOLVED_PULL_REQUEST_MULTIPLE * 10)
        with mock.patch.object(watchdog, "_pull_request_finished", return_value=None):
            self.assertFalse(
                watchdog.owner_finished(
                    {"pull_request": 42, "heartbeat_at": very_old},
                    policy=self.policy,
                )
            )

    def test_a_stuck_lease_is_surfaced_rather_than_silently_held(self) -> None:
        """Held forever and invisible is its own failure."""
        from services.agentops import watchdog

        settings = self.policy["lease"]
        grace = (
            settings["heartbeat_seconds"] * settings["stale_after_missed_heartbeats"]
        )
        stuck = {
            "heartbeat_at": ago(grace * watchdog.UNRESOLVED_PULL_REQUEST_MULTIPLE + 600)
        }
        fresh = {"heartbeat_at": ago(60)}
        self.assertTrue(watchdog.unresolved_too_long(stuck, self.policy))
        self.assertFalse(watchdog.unresolved_too_long(fresh, self.policy))

    def test_the_worker_must_match_the_lane_its_lease_records(self) -> None:
        """A lease exists for a task; that does not make any lane valid for it."""
        from services.agentops import cli

        source = Path(cli.__file__).read_text(encoding="utf-8")
        verify = source.split("def cmd_verify_assignment", 1)[1]
        verify = verify.split(chr(10) + "def ", 1)[0]
        self.assertIn("the lease assigns lane", verify)
        self.assertIn("the lease assigns model", verify)


class TestNinthReviewFindings(unittest.TestCase):
    """Regressions for the ninth review round."""

    def setUp(self) -> None:
        self.policy = policy()

    def test_status_md_is_kept_current_by_reconciliation(self) -> None:
        """AGENTS.md makes STATUS.md the human checkpoint.

        Every worker brief tells the worker to read it, so leaving merged work
        listed as outstanding there would start the next worker from a false
        picture of the repository.
        """
        import shutil
        import tempfile

        from services.agentops import reconcile

        tmp = tempfile.mkdtemp()
        root = Path(tmp)
        self.addCleanup(shutil.rmtree, tmp, True)
        with (root / "STATUS.md").open("w", encoding="utf-8", newline="\n") as handle:
            handle.write("# Shoulder status\n\nHuman prose.\n")

        progress = {"completed_tasks": [1, 14], "completed_blocks": [1]}
        self.assertTrue(reconcile.update_status_file(root, progress, "Task 15"))
        text = (root / "STATUS.md").read_text(encoding="utf-8")
        self.assertIn("Task 15", text)
        self.assertIn("Human prose.", text)

    def test_rewriting_it_is_idempotent(self) -> None:
        import shutil
        import tempfile

        from services.agentops import reconcile

        tmp = tempfile.mkdtemp()
        root = Path(tmp)
        self.addCleanup(shutil.rmtree, tmp, True)
        with (root / "STATUS.md").open("w", encoding="utf-8", newline="\n") as handle:
            handle.write("# Shoulder status\n")

        progress = {"completed_tasks": [1], "completed_blocks": []}
        reconcile.update_status_file(root, progress, "Task 2")
        first = (root / "STATUS.md").read_text(encoding="utf-8")
        self.assertFalse(reconcile.update_status_file(root, progress, "Task 2"))
        self.assertEqual(first, (root / "STATUS.md").read_text(encoding="utf-8"))
        self.assertEqual(first.count(reconcile.STATUS_BEGIN), 1)

    def test_a_replay_cannot_reuse_an_attached_lease(self) -> None:
        """A manual rerun with the exact leased values would otherwise pass."""
        from services.agentops import cli

        source = Path(cli.__file__).read_text(encoding="utf-8")
        verify = source.split("def cmd_verify_assignment", 1)[1]
        verify = verify.split(chr(10) + "def ", 1)[0]
        self.assertIn("is held by worker run", verify)

    def test_the_hand_off_follows_acquisition_not_the_plan(self) -> None:
        """Acquisition can decline and still exit zero."""
        from agentops_fixtures import REPO_ROOT as root

        text = (root / ".github/workflows/agentops-coordinator.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("steps.lease.outputs.acquired == 'true'", text)
        handoff = text.split("Hand the task to its lane", 1)[1]
        self.assertNotIn("steps.plan.outputs.dispatched", handoff)


class TestTenthReviewFindings(unittest.TestCase):
    """Regressions for the tenth review round."""

    def setUp(self) -> None:
        self.policy = policy()

    def test_the_committed_status_file_already_has_its_markers(self) -> None:
        """Without them the first reconciliation appends a second status block
        beside the human one, leaving two sources of truth."""
        from agentops_fixtures import REPO_ROOT as root

        from services.agentops import reconcile

        text = (root / "STATUS.md").read_text(encoding="utf-8")
        self.assertEqual(text.count(reconcile.STATUS_BEGIN), 1)
        self.assertEqual(text.count(reconcile.STATUS_END), 1)
        self.assertIn("## Supervisor checkpoint", text)

    def test_a_blocked_task_leaves_the_candidate_pool(self) -> None:
        """A lease released as blocked is not active, so the active-lease check
        let the task straight back in and the attempt bound meant nothing."""
        import shutil
        import tempfile

        from agentops_fixtures import REPO_ROOT as source

        tmp = tempfile.mkdtemp()
        root = Path(tmp)
        self.addCleanup(shutil.rmtree, tmp, True)
        for relative in ("ops", "docs", "services"):
            shutil.copytree(source / relative, root / relative)

        ctx = coordinator.load_context(root)
        before = coordinator.next_eligible(ctx)
        assert before is not None
        blocked_id = before.task.id

        ctx.tasks.setdefault("leases", {})[str(blocked_id)] = {
            "task_id": blocked_id,
            "state": "blocked",
            "branch": "block-04-t14",
        }
        state.write_json(ctx.paths.tasks, ctx.tasks)

        fresh = coordinator.load_context(root)
        candidate = coordinator.evaluate(fresh, fresh.backlog.tasks[blocked_id])
        self.assertFalse(candidate.eligible)
        self.assertTrue(
            any("BLOCKED_AUTOMATION" in r for r in candidate.reasons),
            candidate.reasons,
        )
        # And the coordinator moves past it rather than stalling.
        following = coordinator.next_eligible(fresh)
        if following is not None:
            self.assertNotEqual(following.task.id, blocked_id)

    def test_the_worker_identity_includes_the_attempt(self) -> None:
        """GITHUB_RUN_ID is unchanged on a re-run; only the attempt increments.

        The two travel as separate flags. Concatenating them was the round-14
        defect: the combined value reached `gh run view`, which takes a bare
        run id, so every liveness query failed and fail-closed froze the lease.
        """
        from agentops_fixtures import REPO_ROOT as root

        text = (root / ".github/workflows/agentops-worker.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn('--run-id "$GITHUB_RUN_ID"', text)
        self.assertIn('--run-attempt "$GITHUB_RUN_ATTEMPT"', text)
        self.assertNotIn("${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}", text)


class TestFourteenthReviewFindings(unittest.TestCase):
    """Regressions for the fourteenth review round."""

    def setUp(self) -> None:
        self.policy = policy()

    def test_the_attempt_is_stored_beside_the_run_id_not_inside_it(self) -> None:
        """`gh run view` takes a bare run id.

        Folding the attempt into the same field made every liveness query fail,
        and because that query fails closed the lease could never be recovered.
        """
        tasks: dict[str, Any] = {"leases": {}}
        leases.acquire(
            tasks,
            self.policy,
            task_id=14,
            owner="run-1",
            branch="block-04-t14",
            assignment=assignment(),
        )
        lease = leases.attach_worker(
            tasks, 14, run_id="123", run_attempt="2", pull_request=None
        )
        self.assertEqual(lease["worker_run_id"], "123")
        self.assertEqual(lease["worker_run_attempt"], "2")

        # And the watchdog asks about the bare id.
        from services.agentops import watchdog

        seen: list[list[str]] = []

        class Result:
            returncode = 0
            stdout = '{"status": "completed"}'

        def fake_run(command: list[str], **_: Any) -> Result:
            seen.append(command)
            return Result()

        with mock.patch("services.agentops.watchdog.subprocess.run", fake_run):
            watchdog.owner_finished(lease, repo="o/r", policy=self.policy)
        self.assertIn(
            ["gh", "run", "view", "123", "--json", "status", "--repo", "o/r"], seen
        )

    def test_the_managed_block_lives_inside_the_supervisor_checkpoint(self) -> None:
        """Seeded below the whole checkpoint, the managed block and the human
        table become two adjacent answers to the same question, and a worker
        reading top-down acts on the stale one."""
        from agentops_fixtures import REPO_ROOT as root

        from services.agentops import reconcile

        text = (root / "STATUS.md").read_text(encoding="utf-8")
        start = text.index("## Supervisor checkpoint")
        marker = text.index(reconcile.STATUS_BEGIN)
        self.assertGreater(marker, start)
        following = text.find(chr(10) + "## ", start + 1)
        self.assertTrue(
            following == -1 or marker < following,
            "the managed block drifted out of the checkpoint section",
        )

    def test_blocking_a_task_shows_up_in_the_live_picture(self) -> None:
        """After a task exhausts its attempts, the picture must stop naming it
        as the next action. That was STATUS.md, now on the protected branch;
        the Control Center reports it instead."""
        import argparse
        import shutil
        import tempfile

        from agentops_fixtures import REPO_ROOT as source

        from services.agentops import cli, control_center

        tmp = tempfile.mkdtemp()
        root = Path(tmp)
        self.addCleanup(shutil.rmtree, tmp, True)
        for relative in ("ops", "docs", "services"):
            shutil.copytree(source / relative, root / relative)

        ctx = coordinator.load_context(root)
        ctx.policy["autonomy"]["enabled"] = True
        state.write_json(ctx.paths.policy, ctx.policy)
        patched = mock.patch.dict(os.environ, {"AUTONOMY_ENABLED": "true"})
        patched.start()
        self.addCleanup(patched.stop)

        candidate = coordinator.next_eligible(ctx)
        assert candidate is not None
        ceiling = int(ctx.policy["escalation"]["max_implementation_attempts"])
        ctx.tasks.setdefault("leases", {})[str(candidate.task.id)] = {
            "task_id": candidate.task.id,
            "state": "assigned",
            "owner": "run-old",
            "branch": "block-04-t15-old",
            "acquired_at": "2000-01-01T00:00:00+00:00",
            "expires_at": "2000-01-01T00:00:00+00:00",
            "heartbeat_at": "2000-01-01T00:00:00+00:00",
            "attempts": ceiling,
        }
        state.write_json(ctx.paths.tasks, ctx.tasks)

        args = argparse.Namespace(
            root=str(root), owner="run-new", run_id="new", repo=None
        )
        cli.cmd_dispatch(args)

        fresh = coordinator.load_context(root)
        self.assertEqual(
            fresh.tasks["leases"][str(candidate.task.id)]["state"], "blocked"
        )
        with mock.patch.object(control_center, "pull_request_checks", return_value=[]):
            page = control_center.render(root, repo=None)
        self.assertIn("BLOCKED_AUTOMATION", page)

    def test_recovering_a_lease_updates_the_live_picture(self) -> None:
        """Recovery puts a task back in the pool, which changes what comes next.

        That used to be written into STATUS.md, which now lives on a protected
        branch nothing may push to. The Control Center carries the live picture
        instead, and it must name the recovered task rather than the one a dead
        worker was holding.
        """
        import shutil
        import tempfile

        from agentops_fixtures import REPO_ROOT as source

        from services.agentops import control_center, watchdog

        tmp = tempfile.mkdtemp()
        root = Path(tmp)
        self.addCleanup(shutil.rmtree, tmp, True)
        for relative in ("ops", "docs", "services"):
            shutil.copytree(source / relative, root / relative)

        ctx = coordinator.load_context(root)
        candidate = coordinator.next_eligible(ctx)
        assert candidate is not None
        # Nothing was ever attached, so liveness is answerable: the owner is
        # provably gone and the sweep may reclaim the lease.
        ctx.tasks.setdefault("leases", {})[str(candidate.task.id)] = {
            "task_id": candidate.task.id,
            "state": "implementing",
            "owner": "run-dead",
            "branch": "block-04-t15-dead",
            "acquired_at": "2000-01-01T00:00:00+00:00",
            "expires_at": "2000-01-01T00:00:00+00:00",
            "heartbeat_at": "2000-01-01T00:00:00+00:00",
            "attempts": 1,
        }
        state.write_json(ctx.paths.tasks, ctx.tasks)

        result = watchdog.sweep(root)
        self.assertTrue(result["recovered"])

        with mock.patch.object(control_center, "pull_request_checks", return_value=[]):
            page = control_center.render(root, repo=None)
        self.assertIn(f"Task {candidate.task.id}", page)

    def test_recovery_does_not_write_the_protected_checkpoint(self) -> None:
        """STATUS.md is on the default branch, which nothing may push to."""
        from services.agentops import watchdog

        source = Path(watchdog.__file__).read_text(encoding="utf-8")
        self.assertNotIn("update_status_file", source)


class TestWorkerFinishedWithoutPullRequest(unittest.TestCase):
    """The first live worker died in under a minute and wedged the loop.

    Its lease stayed `assigned` with `expires_at` 90 minutes out, so nothing
    could touch it until that timeout passed even though the run was provably
    over. These cover the explicit transition that replaces the wait, and --
    more importantly -- every condition under which it must refuse.
    """

    RUN = "34921450581"
    BRANCH = "block-04-t15-coach-judgments"

    def setUp(self) -> None:
        self.policy = policy()
        self.tasks: dict[str, Any] = {"leases": {}}
        leases.acquire(
            self.tasks,
            self.policy,
            task_id=15,
            owner="run-34921416961",
            branch=self.BRANCH,
            assignment=assignment(),
            run_id="34921416961",
        )
        leases.attach_worker(self.tasks, 15, run_id=self.RUN, run_attempt="1")

    def lease(self) -> dict[str, Any]:
        held: dict[str, Any] = self.tasks["leases"]["15"]
        return held

    def recover(self, **overrides: Any) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "run_id": self.RUN,
            "branch": self.BRANCH,
            "failure_class": "provider",
            "pull_request_open": False,
        }
        kwargs.update(overrides)
        return leases.abandon_finished_worker(self.tasks, 15, **kwargs)

    def test_a_finished_worker_with_no_pull_request_frees_the_lease(self) -> None:
        lease = self.recover()
        self.assertEqual(lease["state"], "abandoned")
        self.assertNotIn(lease["state"], leases.ACTIVE_STATES)
        self.assertTrue(lease["abandoned_at"])
        self.assertEqual(lease["abandoned_by_run"], self.RUN)

    def test_the_lease_does_not_have_to_go_stale_first(self) -> None:
        """The whole point: the 90-minute expiry is still in the future."""
        expires = datetime.fromisoformat(self.lease()["expires_at"])
        self.assertGreater(expires, datetime.now(UTC))
        self.assertFalse(leases.is_stale(self.lease(), self.policy))
        self.assertEqual(self.recover()["state"], "abandoned")

    def test_attempt_accounting_survives(self) -> None:
        self.assertEqual(self.lease()["attempts"], 1)
        self.recover()
        self.assertEqual(self.lease()["attempts"], 1)

    def test_a_checkpoint_survives(self) -> None:
        leases.checkpoint(
            self.tasks,
            15,
            "run-34921416961",
            state="implementing",
            commit="abc1234",
            complete=["migration written"],
            remaining=["router"],
        )
        self.recover()
        self.assertEqual(self.lease()["checkpoint"]["commit"], "abc1234")
        self.assertEqual(self.lease()["checkpoint"]["complete"], ["migration written"])

    def test_provider_failure_stays_classified_apart_from_worker_failure(self) -> None:
        self.assertEqual(
            self.recover(failure_class="provider")["failure_class"], "provider"
        )
        self.setUp()
        self.assertEqual(
            self.recover(failure_class="worker")["failure_class"], "worker"
        )
        self.assertNotEqual(
            leases.FAILURE_CLASSES["provider"], leases.FAILURE_CLASSES["worker"]
        )

    def test_an_unknown_failure_class_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            self.recover(failure_class="ci")
        self.assertEqual(self.lease()["state"], "assigned")

    def test_an_open_pull_request_holds_the_lease(self) -> None:
        """The branch is still in play; the repair path owns it, not this."""
        with self.assertRaises(leases.LeaseConflict):
            self.recover(pull_request_open=True)
        self.assertEqual(self.lease()["state"], "assigned")

    def test_an_attached_pull_request_holds_the_lease(self) -> None:
        leases.attach_worker(self.tasks, 15, pull_request=41)
        with self.assertRaises(leases.LeaseConflict):
            self.recover()
        self.assertEqual(self.lease()["state"], "assigned")

    def test_another_run_may_not_free_this_lease(self) -> None:
        """A re-run, or a finalize job reporting late, must not take a branch a
        newer worker now holds. This is the two-writer guard."""
        with self.assertRaises(leases.LeaseConflict) as caught:
            self.recover(run_id="99999999999")
        self.assertIn("attached to worker run", str(caught.exception))
        self.assertEqual(self.lease()["state"], "assigned")

    def test_a_lease_with_no_attached_worker_is_refused(self) -> None:
        """Nothing proves which run this would be freeing."""
        self.lease().pop("worker_run_id")
        with self.assertRaises(leases.LeaseConflict):
            self.recover()

    def test_another_branch_may_not_free_this_lease(self) -> None:
        with self.assertRaises(leases.LeaseConflict):
            self.recover(branch="block-04-t16-something-else")
        self.assertEqual(self.lease()["state"], "assigned")

    def test_a_terminal_lease_is_left_alone(self) -> None:
        """Which is also what makes the caller's retry loop idempotent."""
        self.recover()
        with self.assertRaises(leases.LeaseConflict) as caught:
            self.recover()
        self.assertIn("nothing to recover", str(caught.exception))

    def test_a_merged_lease_is_never_reopened(self) -> None:
        leases.release(self.tasks, 15, "merged")
        with self.assertRaises(leases.LeaseConflict):
            self.recover()
        self.assertEqual(self.lease()["state"], "merged")

    def test_an_unknown_task_is_refused(self) -> None:
        with self.assertRaises(leases.LeaseConflict):
            leases.abandon_finished_worker(
                self.tasks,
                99,
                run_id=self.RUN,
                branch=self.BRANCH,
                failure_class="worker",
                pull_request_open=False,
            )

    def test_completion_is_never_faked(self) -> None:
        """Recovery must not look like success to anything downstream."""
        lease = self.recover()
        self.assertNotEqual(lease["state"], "merged")
        self.assertIsNone(lease.get("pull_request"))


class TestRecoveredLeaseIsRedispatchable(unittest.TestCase):
    """The transition is only worth anything if the coordinator can act on it."""

    RUN = "34921450581"
    BRANCH = "block-04-t15-coach-judgments"

    def setUp(self) -> None:
        self.policy = policy()
        self.tasks: dict[str, Any] = {"leases": {}}
        leases.acquire(
            self.tasks,
            self.policy,
            task_id=15,
            owner="run-1",
            branch=self.BRANCH,
            assignment=assignment(),
            run_id="1",
        )
        leases.attach_worker(self.tasks, 15, run_id=self.RUN)
        leases.checkpoint(
            self.tasks, 15, "run-1", state="implementing", commit="abc1234"
        )
        leases.abandon_finished_worker(
            self.tasks,
            15,
            run_id=self.RUN,
            branch=self.BRANCH,
            failure_class="provider",
            pull_request_open=False,
        )

    def test_the_freed_lease_stops_counting_as_a_live_writer(self) -> None:
        self.assertEqual(leases.active_leases(self.tasks, self.policy), [])

    def test_the_next_attempt_is_permitted_and_counted(self) -> None:
        lease = leases.acquire(
            self.tasks,
            self.policy,
            task_id=15,
            owner="run-2",
            branch=self.BRANCH,
            assignment=assignment(),
            run_id="2",
        )
        self.assertEqual(lease["attempts"], 2)
        self.assertEqual(lease["state"], "assigned")
        self.assertEqual(lease["checkpoint"]["commit"], "abc1234")

    def test_the_attempt_budget_still_ends_the_retrying(self) -> None:
        """Recovery must not become an unbounded redispatch loop."""
        ceiling = int(self.policy["escalation"]["max_implementation_attempts"])
        for attempt in range(2, ceiling + 1):
            leases.acquire(
                self.tasks,
                self.policy,
                task_id=15,
                owner=f"run-{attempt}",
                branch=self.BRANCH,
                assignment=assignment(),
                run_id=str(attempt),
            )
            leases.attach_worker(self.tasks, 15, run_id=f"worker-{attempt}")
            leases.abandon_finished_worker(
                self.tasks,
                15,
                run_id=f"worker-{attempt}",
                branch=self.BRANCH,
                failure_class="provider",
                pull_request_open=False,
            )
        with self.assertRaises(leases.AttemptsExhausted):
            leases.acquire(
                self.tasks,
                self.policy,
                task_id=15,
                owner="run-last",
                branch=self.BRANCH,
                assignment=assignment(),
                run_id="last",
            )


class TestBranchPullRequestQuery(unittest.TestCase):
    """The open-pull-request question the recovery command fails closed on."""

    def _answer(self, returncode: int, stdout: str) -> bool | None:
        import subprocess

        from services.agentops import watchdog

        completed = mock.Mock(returncode=returncode, stdout=stdout)
        with mock.patch.object(subprocess, "run", return_value=completed):
            return watchdog.branch_pull_request_open("block-04-t15", repo="o/r")

    def test_an_open_pull_request_reads_as_open(self) -> None:
        self.assertIs(self._answer(0, '[{"number": 41}]'), True)

    def test_no_pull_request_reads_as_none_open(self) -> None:
        self.assertIs(self._answer(0, "[]"), False)

    def test_a_failed_query_is_unanswerable(self) -> None:
        self.assertIsNone(self._answer(1, ""))

    def test_unparseable_output_is_unanswerable(self) -> None:
        self.assertIsNone(self._answer(0, "not json"))


class TestHotfixReviewFindings(unittest.TestCase):
    """Regressions for the review of the live-bootstrap hotfix."""

    RUN = "34921450581"
    BRANCH = "block-04-t15-coach-judgments"

    def _recovered(self) -> dict[str, Any]:
        tasks: dict[str, Any] = {"leases": {}}
        leases.acquire(
            tasks,
            policy(),
            task_id=15,
            owner="run-1",
            branch=self.BRANCH,
            assignment=assignment(),
            run_id="1",
        )
        leases.attach_worker(tasks, 15, run_id=self.RUN, run_attempt="1")
        leases.abandon_finished_worker(
            tasks,
            15,
            run_id=self.RUN,
            branch=self.BRANCH,
            failure_class="provider",
            pull_request_open=False,
        )
        return tasks

    def test_the_dead_run_is_detached_from_the_lease(self) -> None:
        """Freeing a lease that still names the dead run frees nothing.

        `acquire` rebuilds the next lease from this record and does not clear
        these fields, and `verify-assignment` runs before a worker can attach
        its own, so the successor would be refused as "held by worker run
        <the dead one>" -- every attempt, until the task blocked.
        """
        lease = self._recovered()["leases"]["15"]
        self.assertIsNone(lease.get("worker_run_id"))
        self.assertIsNone(lease.get("worker_run_attempt"))

    def test_the_next_worker_is_accepted_by_verify_assignment(self) -> None:
        """The end-to-end form of the same defect, at the check that would
        have rejected it."""
        tasks = self._recovered()
        leases.acquire(
            tasks,
            policy(),
            task_id=15,
            owner="run-2",
            branch=self.BRANCH,
            assignment=assignment(),
            run_id="2",
        )
        lease = tasks["leases"]["15"]
        # This is the comparison cmd_verify_assignment makes, before the new
        # worker has had any chance to attach its own run.
        attached = lease.get("worker_run_id")
        self.assertFalse(
            attached and str(attached) != "34999999999",
            f"a fresh worker would be refused: lease still names run {attached}",
        )

    def test_repair_and_recovery_detach_the_run_the_same_way(self) -> None:
        source = Path(leases.__file__).read_text(encoding="utf-8")
        for function in ("begin_repair", "abandon_finished_worker"):
            body = source.split(f"def {function}", 1)[1].split("\ndef ", 1)[0]
            with self.subTest(function):
                self.assertIn('lease.pop("worker_run_id", None)', body)
                self.assertIn('lease.pop("worker_run_attempt", None)', body)


class TestPullRequestQueryFailsClosed(unittest.TestCase):
    """A zero exit is not by itself an answer."""

    def _answer(self, returncode: int, stdout: str) -> bool | None:
        import subprocess

        from services.agentops import watchdog

        completed = mock.Mock(returncode=returncode, stdout=stdout)
        with mock.patch.object(subprocess, "run", return_value=completed):
            return watchdog.branch_pull_request_open("block-04-t15", repo="o/r")

    def test_empty_output_is_unanswerable(self) -> None:
        """It used to read as "no pull request" and free the lease."""
        self.assertIsNone(self._answer(0, ""))
        self.assertIsNone(self._answer(0, "   \n"))

    def test_a_non_list_payload_is_unanswerable(self) -> None:
        for payload in ("null", "{}", '{"number": 41}', '"41"'):
            with self.subTest(payload):
                self.assertIsNone(self._answer(0, payload))

    def test_a_real_empty_list_still_means_no_pull_request(self) -> None:
        self.assertIs(self._answer(0, "[]"), False)
