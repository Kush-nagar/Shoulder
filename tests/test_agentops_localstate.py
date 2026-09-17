"""The local runtime's state store.

Two things here are load-bearing. A provider key must never reach disk, so
redaction happens on the way in rather than on the way out. And liveness must
never be asked with `os.kill(pid, 0)`: on Windows that terminates the process
it is asking about, which would make the recovery sweep the thing that kills
the worker it was sent to rescue.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentops_fixtures import REPO_ROOT

from services.agentops import localstate


class LocalStateCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.paths = localstate.ensure(localstate.LocalPaths(self.root))


class TestSecretsNeverReachDisk(LocalStateCase):
    def test_a_live_secret_is_replaced_anywhere_in_a_payload(self) -> None:
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-secret-1"}):
            out = localstate.redact(
                {"env": ["ANTHROPIC_AUTH_TOKEN=sk-or-secret-1"], "n": 1}
            )
        self.assertNotIn("sk-or-secret-1", json.dumps(out))
        self.assertIn(localstate.REDACTED, json.dumps(out))

    def test_an_event_never_records_a_secret(self) -> None:
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-secret-2"}):
            localstate.append_event(
                self.paths, "spawn", argv=["--token", "sk-or-secret-2"]
            )
        self.assertNotIn(
            "sk-or-secret-2", self.paths.events.read_text(encoding="utf-8")
        )

    def test_a_written_document_never_records_a_secret(self) -> None:
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-secret-3"}):
            localstate.write(self.paths.workers, {"note": "key sk-or-secret-3 used"})
        self.assertNotIn(
            "sk-or-secret-3", self.paths.workers.read_text(encoding="utf-8")
        )

    def test_a_short_value_is_not_treated_as_a_secret(self) -> None:
        """Redacting a two-character value would blank out ordinary prose."""
        with mock.patch.dict(os.environ, {"GH_TOKEN": "ab"}):
            self.assertEqual(localstate.redact("a cabbage"), "a cabbage")


class TestDurability(LocalStateCase):
    def test_a_truncated_document_reads_as_the_default(self) -> None:
        self.paths.workers.write_text("{not json", encoding="utf-8")
        self.assertEqual(
            localstate.read(self.paths.workers, {"workers": {}}), {"workers": {}}
        )

    def test_writing_leaves_no_temporary_file_behind(self) -> None:
        localstate.write(self.paths.workers, {"workers": {}})
        leftovers = [
            p.name for p in self.paths.dir.iterdir() if p.name.endswith(".tmp")
        ]
        self.assertEqual(leftovers, [])

    def test_configuration_defaults_survive_a_partial_file(self) -> None:
        localstate.write(self.paths.config, {"provider": "openrouter"})
        config = localstate.load_config(self.paths)
        self.assertEqual(config["provider"], "openrouter")
        self.assertEqual(config["dashboard"]["port"], 4317)
        self.assertEqual(config["roles"]["implement"]["max_turns"], 120)

    def test_a_stored_role_budget_overrides_only_its_own_field(self) -> None:
        localstate.write(self.paths.config, {"roles": {"implement": {"max_turns": 5}}})
        config = localstate.load_config(self.paths)
        self.assertEqual(config["roles"]["implement"]["max_turns"], 5)
        self.assertEqual(config["roles"]["implement"]["timeout_seconds"], 5400)


class TestLiveness(LocalStateCase):
    def test_this_process_is_alive(self) -> None:
        self.assertTrue(localstate.process_alive(os.getpid()))

    def test_an_absent_process_is_not_alive(self) -> None:
        self.assertFalse(localstate.process_alive(4_000_000_000))

    def test_no_pid_is_not_alive(self) -> None:
        self.assertFalse(localstate.process_alive(None))
        self.assertFalse(localstate.process_alive(0))

    def test_a_reused_pid_running_another_image_is_not_our_worker(self) -> None:
        self.assertFalse(
            localstate.process_alive(os.getpid(), image="definitely-not.exe")
        )

    @unittest.skipUnless(sys.platform == "win32", "Windows liveness path")
    def test_windows_liveness_never_calls_os_kill(self) -> None:
        """`os.kill` on Windows terminates for every signal but two console
        events, so a liveness probe written that way kills the worker."""
        with mock.patch.object(os, "kill") as killed:
            localstate.process_alive(os.getpid())
        killed.assert_not_called()

    def test_windows_liveness_reads_tasklist(self) -> None:
        with mock.patch.object(sys, "platform", "win32"):
            with mock.patch.object(subprocess, "run") as run:
                run.return_value = mock.Mock(stdout='"python.exe","4242"')
                self.assertTrue(localstate.process_alive(4242, image="python.exe"))
        self.assertEqual(run.call_args.args[0][0], "tasklist")


class TestUsageAndPruning(LocalStateCase):
    def test_usage_sums_what_the_runs_reported(self) -> None:
        localstate.save_worker(
            self.paths,
            "1",
            {"cost_usd": 0.25, "usage": {"input_tokens": 10, "output_tokens": 2}},
        )
        localstate.save_worker(
            self.paths,
            "2",
            {"cost_usd": 0.75, "usage": {"input_tokens": 5, "output_tokens": 3}},
        )
        totals = localstate.usage_totals(self.paths)
        self.assertAlmostEqual(totals["reported_cost_usd"], 1.0)
        self.assertEqual(totals["input_tokens"], 15)

    def test_old_run_directories_are_pruned_newest_kept(self) -> None:
        for name in ("a", "b", "c"):
            run = self.paths.run_dir(name)
            run.mkdir(parents=True)
            (run / "stdout.jsonl").write_text("{}", encoding="utf-8")
        removed = localstate.prune_runs(self.paths, keep=1)
        self.assertEqual(len(removed), 2)
        self.assertEqual([p.name for p in self.paths.runs.iterdir()], ["c"])


class TestTheRuntimeDirectoryIsIgnored(unittest.TestCase):
    def test_git_ignores_local_runtime_state(self) -> None:
        """Runtime bookkeeping must never show up as a change on a worker's
        branch; if it did, every heartbeat would dirty the diff under review."""
        result = subprocess.run(
            ["git", "check-ignore", "-q", ".agentops/local/workers.json"],
            cwd=REPO_ROOT,
            check=False,
        )
        self.assertEqual(result.returncode, 0, ".agentops must be gitignored")


if __name__ == "__main__":
    unittest.main()
