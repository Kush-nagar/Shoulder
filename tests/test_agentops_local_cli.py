"""The local runtime's command line.

`run` is the only verb that starts work, and the property that matters is that
it obeys the same switch every other writer obeys. The rest are read-only or
record a choice.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from agentops_fixtures import REPO_ROOT

from services.agentops import cli, local, localstate


class CliCase(unittest.TestCase):
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
        self.paths = localstate.ensure(localstate.LocalPaths(self.root))

    def run_cli(self, *args: str) -> dict[str, Any]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            # `--root` is a top-level flag, before the subcommand.
            code = cli.main(["--root", str(self.root), *args])
        self.assertEqual(code, 0, out.getvalue())
        payload: dict[str, Any] = json.loads(out.getvalue())
        return payload


class TestRunObeysTheSwitch(CliCase):
    def test_run_refuses_while_autonomy_is_disabled(self) -> None:
        payload = self.run_cli("run", "--once")
        self.assertFalse(payload["results"][0]["dispatched"])
        self.assertIn("AUTONOMY_ENABLED is false", payload["results"][0]["reason"])

    def test_run_records_that_the_runtime_stopped(self) -> None:
        self.run_cli("run", "--once")
        runtime = localstate.read(self.paths.runtime, {})
        self.assertEqual(runtime["state"], "stopped")

    def test_run_writes_nothing_into_tracked_state(self) -> None:
        tracked = self.root / "ops" / "state" / "tasks.json"
        before = tracked.read_text(encoding="utf-8")
        self.run_cli("run", "--once")
        self.assertEqual(tracked.read_text(encoding="utf-8"), before)


class TestProviderSwitching(CliCase):
    def test_status_reports_available_later_without_a_key(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            payload = self.run_cli("provider", "openrouter")
        self.assertEqual(payload["status"], "AVAILABLE_LATER")
        self.assertIn(local.OPENROUTER_KEY_ENV, payload["how_to_enable"])

    def test_the_choice_is_recorded_but_the_key_is_not(self) -> None:
        with mock.patch.dict(os.environ, {local.OPENROUTER_KEY_ENV: "sk-or-cli"}):
            self.run_cli("provider", "openrouter")
        stored = self.paths.config.read_text(encoding="utf-8")
        self.assertIn("openrouter", stored)
        self.assertNotIn("sk-or-cli", stored)

    def test_switching_back_to_claude_needs_no_key(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            payload = self.run_cli("provider", "claude")
        self.assertEqual(payload["status"], "AVAILABLE")


class TestReadOnlyVerbs(CliCase):
    def test_local_status_reports_the_runtime_and_the_coordinator(self) -> None:
        payload = self.run_cli("local-status")
        self.assertIn("coordinator", payload)
        self.assertIn("runtime", payload)
        self.assertFalse(payload["runtime"]["alive"])

    def test_resume_classifies_what_was_left_behind(self) -> None:
        localstate.save_worker(
            self.paths,
            "15",
            {"task_id": 15, "phase": "implementing", "pid": 4_000_000_000},
        )
        payload = self.run_cli("resume")
        self.assertEqual(payload["workers"][0]["state"], "interrupted")

    def test_stop_says_so_when_nothing_is_running(self) -> None:
        payload = self.run_cli("stop")
        self.assertFalse(payload["stopped"])

    def test_doctor_reports_the_uv_pin_it_needs(self) -> None:
        payload = self.run_cli("doctor")
        self.assertIn("uv", payload)
        self.assertIn("provider", payload)


class TestTheWrappers(unittest.TestCase):
    def test_the_wrappers_only_map_arguments(self) -> None:
        """Logic in two places is logic that eventually disagrees."""
        for name in ("agentops-local.ps1", "agentops-provider.ps1"):
            source = (REPO_ROOT / "scripts" / name).read_text(encoding="utf-8")
            self.assertIn("services.agentops.cli", source, name)

    def test_the_provider_wrapper_never_stores_a_key(self) -> None:
        source = (REPO_ROOT / "scripts" / "agentops-provider.ps1").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("Set-Content", source)
        self.assertIn("OPENROUTER_API_KEY", source)

    def test_every_wrapper_command_exists_in_the_cli(self) -> None:
        # argparse exposes no public reader for subcommand names, and the help
        # text is the same list the wrappers have to agree with.
        help_text = cli.build_parser().format_help()
        for expected in ("run", "serve", "stop", "resume", "local-status", "provider"):
            self.assertIn(expected, help_text, expected)


if __name__ == "__main__":
    unittest.main()
