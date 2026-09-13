"""Workflow syntax, permissions, secret hygiene, and the watchdog."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from typing import Any

from agentops_fixtures import REPO_ROOT, policy

from services.agentops import brief, coordinator, leases, state, watchdog

WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
AGENTOPS_WORKFLOWS = sorted(WORKFLOW_DIR.glob("agentops-*.yml"))
# Actions must be pinned to a full commit SHA, as the existing CI workflow does.
USES = re.compile(r"^\s*-?\s*uses:\s*([^\s@]+)@([^\s#]+)", re.MULTILINE)
SHA = re.compile(r"^[0-9a-f]{40}$")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestWorkflowsExist(unittest.TestCase):
    def test_the_three_control_plane_workflows_are_present(self) -> None:
        names = {p.name for p in AGENTOPS_WORKFLOWS}
        self.assertEqual(
            names,
            {
                "agentops-coordinator.yml",
                "agentops-worker.yml",
                "agentops-watchdog.yml",
            },
        )

    def test_workflows_parse_as_yaml(self) -> None:
        """62. Syntax has to be valid before anything else matters."""
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError:
            self.skipTest("PyYAML is not installed")
        for path in AGENTOPS_WORKFLOWS:
            with self.subTest(path.name):
                document = yaml.safe_load(read(path))
                self.assertIn("jobs", document)
                self.assertTrue(document["jobs"])

    def test_existing_quality_workflow_is_untouched(self) -> None:
        """64. Bootstrap must not disturb the repository's own gate."""
        text = read(WORKFLOW_DIR / "ci.yml")
        self.assertIn("name: Quality", text)
        self.assertIn("./scripts/check.ps1", text)


class TestWorkflowPermissions(unittest.TestCase):
    """63. Least privilege, checked explicitly."""

    def test_every_workflow_denies_permissions_by_default(self) -> None:
        for path in AGENTOPS_WORKFLOWS:
            with self.subTest(path.name):
                self.assertIn(
                    "permissions: {}",
                    read(path),
                    "each workflow must start from no permissions",
                )

    def test_no_workflow_grants_blanket_write_all(self) -> None:
        for path in AGENTOPS_WORKFLOWS:
            with self.subTest(path.name):
                self.assertNotIn("permissions: write-all", read(path))

    def test_no_workflow_uses_pull_request_target(self) -> None:
        """Untrusted fork code must never run with write tokens or secrets."""
        for path in AGENTOPS_WORKFLOWS:
            with self.subTest(path.name):
                self.assertNotIn("pull_request_target", read(path))

    def test_coordinator_cannot_open_pull_requests(self) -> None:
        """The coordinator dispatches; only a worker writes product code."""
        text = read(WORKFLOW_DIR / "agentops-coordinator.yml")
        self.assertNotIn("pull-requests: write", text)

    def test_watchdog_cannot_write_pull_requests(self) -> None:
        text = read(WORKFLOW_DIR / "agentops-watchdog.yml")
        self.assertNotIn("pull-requests: write", text)

    def test_worker_has_the_permissions_it_needs_and_no_more(self) -> None:
        text = read(WORKFLOW_DIR / "agentops-worker.yml")
        for needed in ("contents: write", "pull-requests: write", "id-token: write"):
            self.assertIn(needed, text)
        self.assertNotIn("actions: write", text)

    def test_every_action_is_pinned_to_a_commit_sha(self) -> None:
        for path in AGENTOPS_WORKFLOWS:
            for action, ref in USES.findall(read(path)):
                with self.subTest(f"{path.name}:{action}"):
                    self.assertRegex(ref, SHA, f"{action} is not pinned to a SHA")

    def test_concurrency_prevents_two_writers_on_one_branch(self) -> None:
        text = read(WORKFLOW_DIR / "agentops-worker.yml")
        self.assertIn("concurrency:", text)
        self.assertIn("group: agentops-worker-${{ inputs.branch }}", text)

    def test_coordinator_is_serialised(self) -> None:
        text = read(WORKFLOW_DIR / "agentops-coordinator.yml")
        self.assertIn("group: agentops-coordinator", text)
        self.assertIn("cancel-in-progress: false", text)


class TestWorkflowSecretHygiene(unittest.TestCase):
    def test_secrets_are_referenced_only_through_the_secrets_context(self) -> None:
        literal = re.compile(r"(sk-or-v1-|sk-proj-|ghp_|github_pat_)")
        for path in AGENTOPS_WORKFLOWS:
            with self.subTest(path.name):
                self.assertIsNone(literal.search(read(path)))

    def test_no_workflow_echoes_a_secret(self) -> None:
        bad = re.compile(r"echo[^\n]*secrets\.")
        for path in AGENTOPS_WORKFLOWS:
            with self.subTest(path.name):
                self.assertIsNone(bad.search(read(path)))

    def test_each_lane_uses_its_declared_secret(self) -> None:
        text = read(WORKFLOW_DIR / "agentops-worker.yml")
        for lane in policy()["lanes"].values():
            self.assertIn(f"secrets.{lane['secret']}", text, lane["secret"])

    def test_autonomy_is_guarded_before_any_work_starts(self) -> None:
        """51/61. The worker refuses to run while the kill switch is off."""
        text = read(WORKFLOW_DIR / "agentops-worker.yml")
        self.assertIn("AUTONOMY_ENABLED", text)
        self.assertIn("needs.guard.outputs.allowed == 'true'", text)

    def test_watchdog_only_restarts_work_when_autonomy_is_on(self) -> None:
        text = read(WORKFLOW_DIR / "agentops-watchdog.yml")
        self.assertIn("vars.AUTONOMY_ENABLED == 'true'", text)


class TestWatchdog(unittest.TestCase):
    """60. Recovery of stale leases and elapsed provider cooldowns."""

    def test_a_clean_repository_needs_no_recovery(self) -> None:
        result = watchdog.sweep(REPO_ROOT)
        self.assertEqual(result["recovered"], [])
        self.assertEqual(result["active_leases"], 0)

    def test_idle_is_false_while_autonomy_is_off(self) -> None:
        """The watchdog must not restart work the kill switch has stopped."""
        self.assertFalse(watchdog.sweep(REPO_ROOT)["idle"])

    def test_stale_lease_is_abandoned_and_its_checkpoint_kept(self) -> None:
        from datetime import UTC, datetime, timedelta

        settings = policy()
        tasks: dict[str, Any] = {"leases": {}}
        leases.acquire(
            tasks,
            settings,
            task_id=14,
            owner="worker-a",
            branch="b",
            assignment={"lane": "claude_subscription"},
        )
        leases.checkpoint(
            tasks,
            14,
            "worker-a",
            state="implementing",
            commit="abc1234",
            remaining=["marking UI"],
        )
        window = (
            settings["lease"]["heartbeat_seconds"]
            * settings["lease"]["stale_after_missed_heartbeats"]
        )
        tasks["leases"]["14"]["heartbeat_at"] = (
            datetime.now(UTC) - timedelta(seconds=window + 60)
        ).isoformat(timespec="seconds")

        self.assertTrue(leases.is_stale(tasks["leases"]["14"], settings))
        self.assertEqual(leases.active_leases(tasks, settings), [])
        # The checkpoint is what makes the next worker cheap; it must survive.
        self.assertEqual(tasks["leases"]["14"]["checkpoint"]["commit"], "abc1234")


class TestWorkerBrief(unittest.TestCase):
    """The brief is the worker's entire context; it must be complete and narrow."""

    def setUp(self) -> None:
        self.text = brief.render(REPO_ROOT, 14)

    def test_brief_names_the_task_and_branch(self) -> None:
        self.assertIn("Task 14", self.text)
        self.assertIn("Manual clip marking", self.text)
        self.assertIn("block-04-t14-manual-clip-marking", self.text)

    def test_brief_carries_the_overriding_rules(self) -> None:
        for rule in ("AGENTS.md", "row-level security", "Phase D gate"):
            self.assertIn(rule, self.text)

    def test_brief_states_the_verification_owed(self) -> None:
        self.assertIn("Playwright", self.text)
        self.assertIn("./scripts/check.ps1", self.text)

    def test_brief_limits_reading_to_the_named_documents(self) -> None:
        self.assertIn("docs/03-schema.md", self.text)
        self.assertIn("docs/05-ui.md", self.text)
        self.assertIn("Read nothing else", self.text)
        # A document this task does not name must not be pulled in.
        self.assertNotIn("docs/07-cv.md", self.text)

    def test_brief_protects_the_domain_vocabulary(self) -> None:
        self.assertIn("`observation`", self.text)

    def test_brief_includes_a_checkpoint_when_one_exists(self) -> None:
        ctx = coordinator.load_context(REPO_ROOT)
        ctx.tasks.setdefault("leases", {})["14"] = {
            "task_id": 14,
            "state": "implementing",
            "checkpoint": {
                "state": "implementing",
                "commit": "deadbee",
                "complete": ["migration 0007"],
                "remaining": ["marking UI"],
                "next_action": "write the keyboard handler",
            },
        }
        state.write_json(ctx.paths.tasks, ctx.tasks)
        try:
            text = brief.render(REPO_ROOT, 14)
            self.assertIn("Checkpoint from a previous attempt", text)
            self.assertIn("deadbee", text)
            self.assertIn("write the keyboard handler", text)
        finally:
            state.write_json(
                ctx.paths.tasks,
                {
                    "$comment": "Active task leases. One writer per task, per branch, "
                    "per checkout.",
                    "leases": {},
                },
            )

    def test_unknown_task_is_refused(self) -> None:
        with self.assertRaises(SystemExit):
            brief.render(REPO_ROOT, 999)

    def test_brief_contains_no_secret_material(self) -> None:
        from services.agentops import notify

        self.assertEqual(notify.redact(self.text), self.text)


class TestDryRunEvidence(unittest.TestCase):
    """48. The dry run against the real backlog is the readiness proof."""

    def test_dry_run_selects_task_14_with_a_complete_plan(self) -> None:
        result = coordinator.dry_run(REPO_ROOT)
        self.assertEqual(result["task_id"], 14)
        self.assertEqual(result["block"], "block-04")
        self.assertEqual(result["prerequisites"], [7, 13])
        self.assertEqual(result["branch"], "block-04-t14-manual-clip-marking")
        self.assertIn("Playwright", result["verification"])

    def test_dry_run_is_serialisable_for_a_workflow_summary(self) -> None:
        json.dumps(coordinator.dry_run(REPO_ROOT), default=str)


if __name__ == "__main__":
    unittest.main()
