"""Leases, interruption recovery, bounded retries, and the kill switch."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

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
        """52. Concurrency never exceeds the configured ceiling."""
        self.assertEqual(self.policy["autonomy"]["max_parallel_writers"], 1)
        self._acquire("worker-a", task_id=14)
        with self.assertRaises(leases.LeaseConflict) as raised:
            self._acquire("worker-b", task_id=15)
        self.assertIn("max_parallel_writers", str(raised.exception))

    def test_raising_the_limit_allows_a_second_writer(self) -> None:
        self.policy["autonomy"]["max_parallel_writers"] = 2
        self._acquire("worker-a", task_id=14)
        second = self._acquire("worker-b", task_id=15)
        self.assertEqual(second["owner"], "worker-b")

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

        code = cli.main(["--root", str(REPO_ROOT), "dispatch"])
        self.assertEqual(code, 0)
        ctx = coordinator.load_context(REPO_ROOT)
        self.assertEqual(ctx.tasks.get("leases"), {}, "no lease may be taken")


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

    def test_no_lease_is_committed(self) -> None:
        self.assertEqual(self.ctx.tasks.get("leases"), {})

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
        for lane in ("claude_subscription", "openrouter", "codex_cloud"):
            state.mark_provider(providers, lane, "AVAILABLE", reason="test")
        state.mark_lane_qualified(providers, "codex_cloud", evidence="test")
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
        built = self.plan_for(15)
        assert built.writer is not None, built.blocked_reason
        self.assertEqual(built.writer.lane, "claude_subscription")

    def test_backend_work_prefers_the_other_subscription_lane(self) -> None:
        """Paid credits are the last resort, not the first fallback.

        With Claude cooled, Codex Cloud takes the work because it is also
        subscription-backed. Reaching for metered OpenRouter capacity while an
        included allowance sits unused would be the more expensive choice.
        """
        self.cool("claude_subscription")
        built = self.plan_for(15)
        assert built.writer is not None, built.blocked_reason
        self.assertEqual(built.writer.lane, "codex_cloud")

    def test_backend_work_reaches_openrouter_once_both_subscriptions_cool(
        self,
    ) -> None:
        self.cool("claude_subscription")
        self.cool("codex_cloud")
        built = self.plan_for(15)
        assert built.writer is not None, built.blocked_reason
        self.assertEqual(built.writer.lane, "openrouter")

    def test_frontend_work_waits_when_codex_cools(self) -> None:
        """It must not fall through to a writer the policy forbids."""
        self.cool("codex_cloud")
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

        built = self.plan_for(18)
        assert built.writer is not None, built.blocked_reason
        self.assertEqual(built.writer.lane, "codex_cloud")

    def test_everything_down_blocks_rather_than_improvising(self) -> None:
        for lane in ("claude_subscription", "openrouter", "codex_cloud"):
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

    def test_the_hand_off_commit_does_not_ride_the_task_branch(self) -> None:
        """Delegation leaves the checkout on the task branch.

        Pushing HEAD to main from there would put the branch's starter commit
        on main, and reconcile would read the task as already merged.
        """
        from agentops_fixtures import REPO_ROOT as root

        text = (root / ".github/workflows/agentops-coordinator.yml").read_text(
            encoding="utf-8"
        )
        handoff = text.split("Commit what the hand-off recorded", 1)[1]
        self.assertIn("git checkout -B agentops-state-handoff origin/main", handoff)


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
        leases.acquire(
            ctx.tasks,
            ctx.policy,
            task_id=14,
            owner="run-1",
            branch="block-04-t14",
            assignment={"lane": "codex_cloud"},
        )
        state.write_json(ctx.paths.tasks, ctx.tasks)

        fresh = coordinator.load_context(root)
        task = fresh.backlog.tasks[14]
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
        """GITHUB_RUN_ID is unchanged on a re-run; only the attempt increments."""
        from agentops_fixtures import REPO_ROOT as root

        text = (root / ".github/workflows/agentops-worker.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn('--run-id "${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"', text)
        self.assertNotIn('--run-id "$GITHUB_RUN_ID"', text)
