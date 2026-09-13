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

    def test_no_spend_is_committed(self) -> None:
        self.assertEqual(self.ctx.budget.get("spend"), {})

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
            self.assertFalse(watchdog.owner_finished({"run_id": "123"}))
            run.return_value = mock.Mock(returncode=0, stdout='{"status":"completed"}')
            self.assertTrue(watchdog.owner_finished({"run_id": "123"}))

    def test_an_unanswerable_run_query_does_not_wedge_recovery(self) -> None:
        from unittest import mock

        from services.agentops import watchdog

        self.assertTrue(watchdog.owner_finished({}))
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=1, stdout="")
            self.assertTrue(watchdog.owner_finished({"run_id": "123"}))

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
