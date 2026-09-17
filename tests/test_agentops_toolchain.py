"""Finding the pinned uv, and keeping shared-port checks apart.

The uv on this workstation's PATH is 0.11.28 and the repository pins 0.12.10.
Running the wrong one silently is the failure this guards: it either refuses or
resolves a different dependency set than CI, and either way the local result
stops meaning what it claims to mean.
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

from services.agentops import localstate, toolchain

# Run in a separate interpreter so the lock is contended across processes,
# which is the only way to prove a file lock does its job.
CHILD_TRY = """
import sys
sys.path.insert(0, r"{repo}")
from pathlib import Path
from services.agentops import localstate, toolchain
paths = localstate.LocalPaths(Path(r"{root}"))
try:
    with toolchain.infra_lock(paths, owner="other-process"):
        print("TOOK")
except toolchain.LockBusy:
    print("REFUSED")
"""

CHILD_TAKE = """
import sys
sys.path.insert(0, r"{repo}")
from pathlib import Path
from services.agentops import localstate, toolchain
paths = localstate.LocalPaths(Path(r"{root}"))
with toolchain.infra_lock(paths, owner="other-process"):
    print("TOOK")
"""

PYPROJECT = """
[tool.uv]
required-version = "==0.12.10"
"""


class ToolchainCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
        self.paths = localstate.ensure(localstate.LocalPaths(self.root))
        self.uv_name = toolchain._binary_names()[0]
        self.binary = self.root / "tools" / self.uv_name
        self.binary.parent.mkdir(parents=True, exist_ok=True)
        self.binary.write_text("", encoding="utf-8")
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)
        os.environ.pop(toolchain.UV_ENV_OVERRIDE, None)


class TestTheRepositoryPin(ToolchainCase):
    def test_the_pin_is_read_from_pyproject(self) -> None:
        self.assertEqual(toolchain.required_version(self.root), "0.12.10")

    def test_a_repository_without_a_pin_is_an_error(self) -> None:
        (self.root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        with self.assertRaises(toolchain.UvUnavailable):
            toolchain.required_version(self.root)


class TestResolvingUv(ToolchainCase):
    def test_a_wrong_version_is_rejected_with_an_actionable_message(self) -> None:
        """PATH uv 0.11.28 is the live case: it must never silently run."""
        os.environ[toolchain.UV_ENV_OVERRIDE] = str(self.binary)
        with self.assertRaises(toolchain.UvUnavailable) as raised:
            toolchain.resolve_uv(self.root, self.paths, probe=lambda p: "uv 0.11.28")
        message = str(raised.exception)
        self.assertIn("0.12.10", message)
        self.assertIn("0.11.28", message)
        self.assertIn(toolchain.UV_ENV_OVERRIDE, message)

    def test_a_matching_binary_is_accepted_and_cached(self) -> None:
        os.environ[toolchain.UV_ENV_OVERRIDE] = str(self.binary)
        found = toolchain.resolve_uv(
            self.root, self.paths, probe=lambda p: "uv 0.12.10"
        )
        self.assertEqual(found, self.binary)
        self.assertEqual(
            localstate.load_config(self.paths)["uv_path"], str(self.binary)
        )

    def test_the_environment_override_is_tried_before_anything_else(self) -> None:
        repo_tools = self.root / ".tools" / self.uv_name
        repo_tools.parent.mkdir(parents=True, exist_ok=True)
        repo_tools.write_text("", encoding="utf-8")
        os.environ[toolchain.UV_ENV_OVERRIDE] = str(self.binary)
        order = [source for source, _ in toolchain.candidates(self.root, {})]
        self.assertEqual(order[0], f"${toolchain.UV_ENV_OVERRIDE}")

    def test_configuration_is_tried_before_the_repository_copy(self) -> None:
        repo_tools = self.root / ".tools" / self.uv_name
        repo_tools.parent.mkdir(parents=True, exist_ok=True)
        repo_tools.write_text("", encoding="utf-8")
        sources = [
            source
            for source, _ in toolchain.candidates(
                self.root, {"uv_path": str(self.binary)}
            )
        ]
        self.assertLess(
            sources.index("config.json uv_path"), sources.index("repository .tools")
        )

    def test_a_sibling_worktree_copy_is_discovered(self) -> None:
        """The pinned binary is gitignored, so a fresh worktree never has it
        while the checkout next door does."""
        sibling = self.root.parent / (self.root.name + "-sibling")
        (sibling / ".tools").mkdir(parents=True, exist_ok=True)
        (sibling / ".tools" / self.uv_name).write_text("", encoding="utf-8")
        self.addCleanup(
            lambda: __import__("shutil").rmtree(sibling, ignore_errors=True)
        )
        listing = f"worktree {self.root}\n\nworktree {sibling}\n"
        with mock.patch.object(subprocess, "run") as run:
            run.return_value = mock.Mock(stdout=listing, returncode=0)
            sources = dict(
                (source, path) for source, path in toolchain.candidates(self.root, {})
            )
        self.assertIn(f"worktree {sibling.name}", sources)

    def test_a_missing_candidate_is_skipped_not_fatal(self) -> None:
        os.environ[toolchain.UV_ENV_OVERRIDE] = str(self.root / "nope" / self.uv_name)
        with self.assertRaises(toolchain.UvUnavailable) as raised:
            toolchain.resolve_uv(self.root, self.paths, probe=lambda p: "uv 0.11.28")
        self.assertIn("missing", str(raised.exception))


class TestTheInfrastructureLock(ToolchainCase):
    def test_a_second_holder_is_refused_while_the_first_is_alive(self) -> None:
        with toolchain.infra_lock(self.paths, owner="a"):
            with self.assertRaises(toolchain.LockBusy):
                with toolchain.infra_lock(self.paths, owner="b"):
                    pass

    def test_the_lock_is_released_on_the_way_out(self) -> None:
        with toolchain.infra_lock(self.paths, owner="a"):
            pass
        with toolchain.infra_lock(self.paths, owner="b") as taken:
            self.assertFalse(taken["recovered"])

    def test_the_lock_is_released_even_when_the_check_raises(self) -> None:
        with self.assertRaises(ValueError):
            with toolchain.infra_lock(self.paths, owner="a"):
                raise ValueError("check blew up")
        self.assertFalse((self.paths.locks / toolchain.LOCK_NAME).exists())

    def test_a_dead_owner_cannot_block_the_machine_forever(self) -> None:
        self.paths.locks.mkdir(parents=True, exist_ok=True)
        (self.paths.locks / toolchain.LOCK_NAME).write_text(
            json.dumps(
                {
                    "owner": "crashed",
                    "pid": 999_999,
                    "started_at": localstate.now(),
                }
            ),
            encoding="utf-8",
        )
        with toolchain.infra_lock(self.paths, owner="b") as taken:
            self.assertTrue(taken["recovered"])
            self.assertIn("gone", taken["recovered_from"]["reason"])

    def test_an_owner_past_the_ceiling_loses_the_lock(self) -> None:
        self.paths.locks.mkdir(parents=True, exist_ok=True)
        (self.paths.locks / toolchain.LOCK_NAME).write_text(
            json.dumps(
                {
                    "owner": "hung",
                    "pid": os.getpid(),
                    "started_at": "2020-01-01T00:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )
        with toolchain.infra_lock(self.paths, owner="b", ttl_seconds=60) as taken:
            self.assertTrue(taken["recovered"])

    def test_recovering_a_lock_is_recorded_as_an_event(self) -> None:
        self.paths.locks.mkdir(parents=True, exist_ok=True)
        (self.paths.locks / toolchain.LOCK_NAME).write_text(
            json.dumps({"owner": "crashed", "pid": 999_999}), encoding="utf-8"
        )
        with toolchain.infra_lock(self.paths, owner="b"):
            pass
        kinds = [event["kind"] for event in localstate.events(self.paths)]
        self.assertIn("infra_lock_recovered", kinds)


class TestWhatTheLockCovers(unittest.TestCase):
    def test_the_smoke_gate_is_serialised(self) -> None:
        """check.ps1 starts a web server for the smoke suite: a port."""
        self.assertTrue(toolchain.needs_infra_lock(["pwsh", "scripts/check.ps1"]))

    def test_infrastructure_scripts_are_serialised(self) -> None:
        for script in ("check-db.ps1", "check-storage.ps1", "check-player.ps1"):
            self.assertTrue(toolchain.needs_infra_lock([f"scripts/{script}"]), script)

    def test_lightweight_checks_run_unlocked(self) -> None:
        """Serialising these would make two workers sequential for no reason."""
        self.assertFalse(
            toolchain.needs_infra_lock(["uv", "run", "ruff", "check", "."])
        )
        self.assertFalse(
            toolchain.needs_infra_lock(["uv", "run", "python", "-m", "unittest"])
        )


class TestRunningChecks(ToolchainCase):
    def test_the_first_failure_stops_the_run(self) -> None:
        calls: list[list[str]] = []

        def runner(command, **kwargs):  # type: ignore[no-untyped-def]
            calls.append(command)
            return mock.Mock(returncode=1, stdout="boom", stderr="")

        result = toolchain.run_commands(self.root, [["a"], ["b"]], runner=runner)
        self.assertFalse(result["ok"])
        self.assertEqual(result["failed"], ["a"])
        self.assertEqual(calls, [["a"]])

    def test_the_fast_checks_are_the_python_gate(self) -> None:
        commands = toolchain.fast_check_commands(Path("uv"))
        flat = [" ".join(c) for c in commands]
        self.assertTrue(any("ruff" in c for c in flat))
        self.assertTrue(any("mypy" in c for c in flat))
        self.assertTrue(any("unittest" in c for c in flat))
        self.assertFalse(any(toolchain.needs_infra_lock(c) for c in commands))


class TestTheLockUnderContention(ToolchainCase):
    """The three windows a review found, each closed by construction.

    A lock that can be held twice is worse than no lock: the failure it
    produces is a port collision inside somebody else's test output.
    """

    def holder(self, **fields: object) -> None:
        self.paths.locks.mkdir(parents=True, exist_ok=True)
        (self.paths.locks / toolchain.LOCK_NAME).write_text(
            json.dumps(fields), encoding="utf-8"
        )

    def test_a_live_holder_with_an_unreadable_record_keeps_the_lock(self) -> None:
        """An empty or partial record used to read as a dead owner, so a
        second verification could start while the first was running."""
        self.holder()
        with self.assertRaises(toolchain.LockBusy):
            with toolchain.infra_lock(self.paths, owner="b"):
                pass

    def test_a_live_holder_with_no_start_time_keeps_the_lock(self) -> None:
        self.holder(owner="alive", pid=os.getpid())
        with self.assertRaises(toolchain.LockBusy):
            with toolchain.infra_lock(self.paths, owner="b"):
                pass

    def test_a_holder_with_a_malformed_start_time_keeps_the_lock(self) -> None:
        self.holder(owner="alive", pid=os.getpid(), started_at="not a timestamp")
        with self.assertRaises(toolchain.LockBusy):
            with toolchain.infra_lock(self.paths, owner="b"):
                pass

    def test_the_lock_file_never_appears_without_its_contents(self) -> None:
        """The publish is atomic, so a concurrent reader cannot see `{}` and
        conclude the holder is dead."""
        with toolchain.infra_lock(self.paths, owner="a"):
            holder = localstate.read(self.paths.locks / toolchain.LOCK_NAME, {})
        self.assertEqual(holder["owner"], "a")
        self.assertTrue(str(holder.get("pid") or "").isdigit())
        self.assertTrue(holder.get("token"))

    def test_an_overrunning_holder_does_not_delete_its_successor(self) -> None:
        """Releasing whatever is there would remove the next holder's claim
        and let a third verification start alongside it."""
        lock_path = self.paths.locks / toolchain.LOCK_NAME
        with toolchain.infra_lock(self.paths, owner="first"):
            # The successor takes the lock while the first is still inside.
            lock_path.write_text(
                json.dumps(
                    {
                        "owner": "second",
                        "token": "other-token",
                        "pid": os.getpid(),
                        "started_at": localstate.now(),
                    }
                ),
                encoding="utf-8",
            )
        self.assertTrue(lock_path.exists(), "the successor's lock was deleted")
        self.assertEqual(localstate.read(lock_path, {})["owner"], "second")

    def test_only_one_of_two_contenders_can_take_a_stale_lock(self) -> None:
        """Both may classify it as stale; only one may end up owning it."""
        self.holder(owner="crashed", pid=999_999, started_at=localstate.now())
        taken: list[str] = []

        first = toolchain.infra_lock(self.paths, owner="a")
        first.__enter__()
        taken.append("a")
        try:
            with self.assertRaises(toolchain.LockBusy):
                with toolchain.infra_lock(self.paths, owner="b"):
                    taken.append("b")
        finally:
            first.__exit__(None, None, None)
        self.assertEqual(taken, ["a"])

    def test_the_lock_is_free_again_after_the_owner_leaves(self) -> None:
        with toolchain.infra_lock(self.paths, owner="a"):
            pass
        with toolchain.infra_lock(self.paths, owner="b") as second:
            self.assertFalse(second["recovered"])

    def test_a_real_second_process_is_refused_while_the_lock_is_held(self) -> None:
        """The cross-process case the file lock exists for."""
        script = CHILD_TRY.format(repo=str(REPO_ROOT), root=str(self.root))
        with toolchain.infra_lock(self.paths, owner="holder"):
            result = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                check=False,
                cwd=str(REPO_ROOT),
                timeout=120,
            )
        self.assertIn("REFUSED", result.stdout, result.stdout + result.stderr)

    def test_a_second_process_may_take_it_once_it_is_released(self) -> None:
        script = CHILD_TAKE.format(repo=str(REPO_ROOT), root=str(self.root))
        with toolchain.infra_lock(self.paths, owner="holder"):
            pass
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=False,
            cwd=str(REPO_ROOT),
            timeout=120,
        )
        self.assertIn("TOOK", result.stdout, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
