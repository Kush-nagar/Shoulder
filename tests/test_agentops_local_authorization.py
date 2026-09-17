"""Local execution is a different permission from cloud autonomy.

Reading one switch for both is what made the local runtime unusable: the only
way to run a worker on this workstation was to grant unattended writes in
GitHub Actions on credentials nobody is watching. These are separate
permissions with separate blast radii, and this file is what keeps them apart.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from agentops_fixtures import REPO_ROOT

from services.agentops import dashboard, governance, local, localstate, state


class AuthorizationCase(unittest.TestCase):
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
        self.policy_path = self.root / "ops" / "policy.json"
        self.policy_before = self.policy_path.read_text(encoding="utf-8")
        self.paths = localstate.ensure(localstate.LocalPaths(self.root))

    def policy(self) -> dict[str, Any]:
        loaded: dict[str, Any] = json.loads(
            self.policy_path.read_text(encoding="utf-8")
        )
        return loaded


class TestCloudAutonomyIsUntouched(AuthorizationCase):
    def test_the_shipped_policy_has_cloud_autonomy_off(self) -> None:
        self.assertFalse(self.policy()["autonomy"]["enabled"])

    def test_enabling_local_execution_does_not_change_cloud_policy(self) -> None:
        local.enable_local(self.paths, by="test")
        self.assertEqual(
            self.policy_path.read_text(encoding="utf-8"), self.policy_before
        )
        self.assertFalse(state.autonomy_enabled(self.policy()))

    def test_a_whole_local_run_never_writes_the_policy_file(self) -> None:
        local.enable_local(self.paths, by="test")
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
        with mock.patch.object(local, "run_worker") as worker:
            worker.return_value = {
                "ok": False,
                "outcome": "failed",
                "run_id": "r",
                "usage": {},
                "cost_usd": 0.0,
            }
            local.run_once(self.root, self.paths)
        self.assertEqual(
            self.policy_path.read_text(encoding="utf-8"), self.policy_before
        )

    def test_the_local_runtime_holds_no_code_that_writes_the_policy(self) -> None:
        """The guarded file is human-edited. Nothing local may set the gate."""
        for name in ("local.py", "localstate.py", "cli.py", "dashboard.py"):
            source = (REPO_ROOT / "services" / "agentops" / name).read_text(
                encoding="utf-8"
            )
            self.assertNotIn('"autonomy"] =', source, name)
            self.assertNotIn("autonomy.enabled =", source, name)

    def test_policy_is_still_a_guarded_path(self) -> None:
        """The cloud workflow guard is unchanged by any of this."""
        self.assertEqual(
            governance.violations(["ops/policy.json"]), ["ops/policy.json"]
        )
        self.assertEqual(
            governance.violations([".github/workflows/agentops-worker.yml"]),
            [".github/workflows"],
        )

    def test_the_cloud_dispatch_command_still_reads_the_cloud_switch(self) -> None:
        """`dispatch` is the cloud path and must keep refusing."""
        source = (REPO_ROOT / "services" / "agentops" / "cli.py").read_text(
            encoding="utf-8"
        )
        dispatch = source[
            source.index("def cmd_dispatch") : source.index("def cmd_repair")
        ]
        self.assertIn("state.autonomy_enabled", dispatch)


class TestLocalIntentIsRequired(AuthorizationCase):
    def test_without_explicit_intent_nothing_runs(self) -> None:
        result = local.run_once(self.root, self.paths)
        self.assertFalse(result["dispatched"])
        self.assertIn("local execution is not enabled", result["reason"])

    def test_with_explicit_intent_the_cloud_switch_no_longer_blocks_it(self) -> None:
        """Cloud autonomy off, local runtime started: work may run locally."""
        local.enable_local(self.paths, by="test")
        self.assertFalse(state.autonomy_enabled(self.policy()))
        with mock.patch.object(local, "local_plan") as planned:
            planned.return_value = local.LocalPlan(
                candidate=mock.Mock(),
                classification=mock.Mock(),
                capability_class="ROUTINE_CODING",
                branch="b",
                writer=None,
                blocked_reason="stop here, the point is that it got this far",
            )
            result = local.run_once(self.root, self.paths)
        self.assertFalse(result["dispatched"])
        self.assertNotIn("local execution is not enabled", result["reason"])
        planned.assert_called_once()

    def test_importing_the_module_does_not_authorise_anything(self) -> None:
        """An import is not intent. Nothing may start work as a side effect."""
        fresh = localstate.ensure(localstate.LocalPaths(self.root))
        enabled, _ = local.local_authorized(localstate.load_config(fresh))
        self.assertFalse(enabled)

    def test_disabling_stops_local_scheduling_without_touching_cloud_policy(
        self,
    ) -> None:
        local.enable_local(self.paths, by="test")
        local.disable_local(self.paths)
        enabled, _ = local.local_authorized(localstate.load_config(self.paths))
        self.assertFalse(enabled)
        self.assertEqual(
            self.policy_path.read_text(encoding="utf-8"), self.policy_before
        )

    def test_intent_survives_a_restart(self) -> None:
        """A crashed coordinator that the operator restarts should not have to
        be re-authorised; a stopped one should."""
        local.enable_local(self.paths, by="test")
        reopened = localstate.LocalPaths(self.root)
        enabled, why = local.local_authorized(localstate.load_config(reopened))
        self.assertTrue(enabled)
        self.assertIn("test", why)

    def test_the_authorisation_lives_only_in_ignored_local_state(self) -> None:
        local.enable_local(self.paths, by="test")
        self.assertIn(".agentops", str(self.paths.config))
        stored = json.loads(self.paths.config.read_text(encoding="utf-8"))
        self.assertTrue(stored["local_enabled"])


class TestTheDashboardCannotStartWork(AuthorizationCase):
    def test_rendering_the_dashboard_does_not_authorise_execution(self) -> None:
        dashboard.snapshot(self.root, self.paths)
        enabled, _ = local.local_authorized(localstate.load_config(self.paths))
        self.assertFalse(enabled)

    def test_the_dashboard_reports_both_permissions_separately(self) -> None:
        data = dashboard.snapshot(self.root, self.paths)
        self.assertIn("local_execution", data)
        self.assertIn("cloud_autonomy_enabled", data["coordinator"])

    def test_the_dashboard_module_never_calls_the_runner(self) -> None:
        source = (REPO_ROOT / "services" / "agentops" / "dashboard.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("run_once", source)
        self.assertNotIn("enable_local", source)


if __name__ == "__main__":
    unittest.main()
