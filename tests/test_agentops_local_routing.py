"""Choosing, and re-choosing, who does the work locally.

The router is the authority and is not replaced here. What the local layer adds
is two constraints it cannot know about -- whether a harness is installed on
this machine, and whether an operator has approved a model -- and an escalation
path that can cross provider families when a model keeps failing.
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest import mock

from agentops_fixtures import REPO_ROOT, installed_harnesses

from services.agentops import approvals, cli, coordinator, local, localstate


class RoutingCase(unittest.TestCase):
    def planned(self, **kwargs: Any) -> Any:
        """A plan whose writer is present, asserted rather than assumed."""
        plan = local.local_plan(self.ctx, self.candidate, self.store, **kwargs)
        self.assertIsNotNone(plan.writer, plan.blocked_reason)
        return plan

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
        config = localstate.load_config(self.paths)
        config["worktree_root"] = str(Path(self.tmp.name) / "agents")
        localstate.save_config(self.paths, config)
        local.enable_local(self.paths, by="test")
        self.ctx = coordinator.load_context(self.root)
        self.ctx.tasks = local.load_leases(self.root, self.paths)
        self.candidate = coordinator.next_eligible(self.ctx)
        self.store = approvals.load(self.paths)
        self.enterContext(installed_harnesses(claude=True, opencode=False))


class TestHarnessAvailabilityShapesTheChoice(RoutingCase):
    def test_a_lane_whose_harness_is_missing_is_excluded(self) -> None:
        """Choosing a lane that cannot start wastes an attempt on discovering
        the harness is not installed."""
        with installed_harnesses(claude=False, opencode=False):
            unusable = local.unavailable_lanes(self.ctx.policy)
        self.assertIn("openrouter", unusable)
        self.assertIn("claude_subscription", unusable)

    def test_cloud_only_lanes_are_never_chosen_locally(self) -> None:
        unusable = local.unavailable_lanes(self.ctx.policy)
        self.assertIn("codex_cloud", unusable)
        self.assertIn("cloud", unusable["codex_cloud"])

    def test_an_installed_harness_leaves_its_lane_usable(self) -> None:
        unusable = local.unavailable_lanes(self.ctx.policy)
        self.assertNotIn("claude_subscription", unusable)

    def test_a_plan_records_why_a_lane_was_not_used(self) -> None:
        plan = self.planned()
        self.assertTrue(any("codex" in r for r in plan.rejections))


class TestApprovalReachesThePlan(RoutingCase):
    def test_an_unapproved_openrouter_model_is_not_planned(self) -> None:
        plan = self.planned()
        self.assertNotEqual(plan.writer.lane, "openrouter")

    def test_the_plan_reports_the_capability_class_it_gated_on(self) -> None:
        plan = self.planned()
        self.assertIn(plan.capability_class, self.ctx.policy["capability_classes"])


class TestReviewerSelection(RoutingCase):
    def test_a_reviewer_is_always_chosen(self) -> None:
        plan = self.planned()
        self.assertIsNotNone(plan.reviewer)

    def test_a_same_family_reviewer_is_labelled_as_not_independent(self) -> None:
        """With one provider family installed there is no other family to ask.
        Reviewing anyway and saying so beats skipping review."""
        plan = self.planned()
        if plan.reviewer and plan.reviewer.lane == plan.writer.lane:
            self.assertFalse(plan.reviewer_independent)
        else:
            self.assertTrue(plan.reviewer_independent)

    def test_a_replaced_writer_gets_a_reviewer_independent_of_it(self) -> None:
        """A failover swaps the writer, and independence follows the swap.

        Task 19: Codex ran out of allowance mid-task, Claude took the work
        over, and the reviewer chosen for Codex was Claude -- so Claude
        reviewed its own diff while the record still reported the review as
        independent. Asking with the writer that actually wrote is what keeps
        the claim true.
        """
        first = self.planned()
        assert first.reviewer is not None
        took_over = replace(first.reviewer)
        replanned = local.local_plan(
            self.ctx, self.candidate, self.store, writer=took_over
        )
        assert replanned.writer is not None
        assert replanned.reviewer is not None
        self.assertEqual(replanned.writer.lane, took_over.lane)
        if replanned.reviewer_independent:
            self.assertNotEqual(replanned.reviewer.lane, took_over.lane)

    def test_an_overridden_writer_is_used_rather_than_chosen(self) -> None:
        first = self.planned()
        replanned = local.local_plan(
            self.ctx, self.candidate, self.store, writer=first.writer
        )
        self.assertIs(replanned.writer, first.writer)

    def test_the_reviewer_uses_the_same_capability_class_as_the_writer(self) -> None:
        """Risk already chose the class; a separate review tier would either
        under-resource a critical review or waste capability on a trivial one."""
        plan = self.planned()
        self.assertEqual(plan.reviewer.capability_class, plan.writer.capability_class)


class TestCrossFamilyEscalation(RoutingCase):
    def test_a_later_attempt_can_leave_the_lane_that_kept_failing(self) -> None:
        first = self.planned()
        escalated = local.local_plan(
            self.ctx,
            self.candidate,
            self.store,
            escalations=2,
            exclude_lanes=frozenset({first.writer.lane}),
        )
        self.assertTrue(
            escalated.writer is None or escalated.writer.lane != first.writer.lane
        )

    def test_effort_escalates_before_the_lane_does(self) -> None:
        first = self.planned()
        second = self.planned(escalations=1)
        self.assertEqual(second.writer.lane, first.writer.lane)

    def test_a_transition_is_persisted_with_both_sides_and_the_harness(self) -> None:
        recorded: list[dict[str, Any]] = []

        def worker(root, paths, **kwargs):  # type: ignore[no-untyped-def]
            recorded.append({"model": kwargs["model"], "role": kwargs["role"]})
            return {
                "ok": False,
                "outcome": "failed",
                "run_id": f"r{len(recorded)}",
                "usage": {},
                "cost_usd": 0.0,
                "last_action": "",
            }

        with mock.patch.object(local, "run_worker", side_effect=worker):
            result = local.run_once(self.root, self.paths)

        self.assertGreater(len(recorded), 1, "it should have retried")
        events = [e for e in localstate.events(self.paths) if e["kind"] == "escalation"]
        self.assertTrue(events)
        for field in ("previous_model", "next_model", "harness", "failure"):
            self.assertIn(field, events[0])
        self.assertTrue(result["escalations"])

    def test_escalation_stops_at_the_policy_ceiling(self) -> None:
        def worker(root, paths, **kwargs):  # type: ignore[no-untyped-def]
            return {
                "ok": False,
                "outcome": "failed",
                "run_id": "r",
                "usage": {},
                "cost_usd": 0.0,
                "last_action": "",
            }

        with mock.patch.object(local, "run_worker", side_effect=worker):
            result = local.run_once(self.root, self.paths)
        ceiling = int(self.ctx.policy["escalation"]["max_implementation_attempts"])
        attempts = [p for p in result["phases"] if p["phase"] == "implementing"]
        self.assertLessEqual(len(attempts), ceiling)


class TestTheCommands(RoutingCase):
    def run_cli(self, *args: str) -> dict[str, Any]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["--root", str(self.root), *args])
        self.assertEqual(code, 0, out.getvalue())
        payload: dict[str, Any] = json.loads(out.getvalue())
        return payload

    def test_models_reports_approval_and_harnesses(self) -> None:
        payload = self.run_cli("models")
        self.assertIn("approval", payload)
        self.assertIn("harnesses", payload)
        self.assertIn("candidates", payload)

    def test_approving_a_model_is_recorded(self) -> None:
        payload = self.run_cli("approve-model", "deepseek/deepseek-v3", "APPROVED")
        self.assertEqual(payload["state"], "APPROVED")
        store = approvals.load(self.paths)
        self.assertEqual(approvals.state_of(store, "deepseek/deepseek-v3"), "APPROVED")

    def test_doctor_reports_both_permissions_and_both_harnesses(self) -> None:
        payload = self.run_cli("doctor")
        self.assertIn("local_execution", payload)
        self.assertIn("cloud_autonomy", payload)
        self.assertIn("opencode", payload["harnesses"])

    def test_evaluate_refuses_an_unapproved_model_without_spending_anything(
        self,
    ) -> None:
        payload = self.run_cli("evaluate", "deepseek/deepseek-v3")
        self.assertIn("skipped", payload["evaluation"][0])

    def test_evaluate_allows_a_canary_model(self) -> None:
        store = approvals.load(self.paths)
        approvals.set_state(self.paths, store, "deepseek/deepseek-v3", approvals.CANARY)
        with mock.patch.object(local, "evaluate_model", return_value={"ok": True}):
            payload = self.run_cli("evaluate", "deepseek/deepseek-v3")
        self.assertNotIn("skipped", payload["evaluation"][0])


if __name__ == "__main__":
    unittest.main()
