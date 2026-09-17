"""The defects a review found after the first verification pass.

Each class here is a defect that was real, reachable, and not caught by the
tests that existed: governance going blind once a worker commits, a hard
timeout that only applied to talkative workers, a diagnostic run producing
something indistinguishable from reviewed work, a finished task being handed
straight back to a new worker, and a read-only page writing to disk.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from agentops_fixtures import REPO_ROOT, installed_harnesses

from services.agentops import (
    approvals,
    cli,
    dashboard,
    governance,
    leases,
    local,
    localstate,
)


def git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )


class RepoCase(unittest.TestCase):
    """A real git repository, because these defects are about git ranges."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "repo"
        (self.root / "ops" / "state").mkdir(parents=True)
        (self.root / "docs" / "projects").mkdir(parents=True)
        (self.root / "scripts").mkdir(parents=True)
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
        (self.root / "README.md").write_text("start\n", encoding="utf-8")
        for args in (
            ("init", "-q"),
            ("config", "user.email", "t@example.com"),
            ("config", "user.name", "Test"),
            ("add", "-A"),
            ("commit", "-qm", "baseline"),
        ):
            git(self.root, *args)
        self.paths = localstate.ensure(localstate.LocalPaths(self.root))
        config = localstate.load_config(self.paths)
        config["worktree_root"] = str(Path(self.tmp.name) / "agents")
        localstate.save_config(self.paths, config)
        local.enable_local(self.paths, by="test")
        self.enterContext(installed_harnesses(claude=True, opencode=False))

    def worktree_for(self, branch: str = "task-branch") -> tuple[Path, str]:
        config = localstate.load_config(self.paths)
        path = local.worktree_path(self.root, config, branch)
        created = local.create_worktree(self.root, branch, path)
        return path, str(created["base_sha"])

    def commit_in(self, worktree: Path, message: str) -> None:
        git(worktree, "add", "-A")
        git(worktree, "commit", "-qm", message)


class TestGovernanceSurvivesWorkerCommits(RepoCase):
    """`HEAD...HEAD` is empty the moment a worker commits, so a committed edit
    to a guarded path reached the governance check as no change at all."""

    def test_a_baseline_is_captured_before_the_worker_runs(self) -> None:
        _, base = self.worktree_for()
        self.assertTrue(base)
        self.assertEqual(len(base), 40)

    def test_uncommitted_work_is_visible(self) -> None:
        worktree, base = self.worktree_for()
        (worktree / "new.py").write_text("x\n", encoding="utf-8")
        self.assertIn("new.py", local.changed_paths(self.root, worktree, base=base))

    def test_one_commit_is_visible(self) -> None:
        worktree, base = self.worktree_for()
        (worktree / "new.py").write_text("x\n", encoding="utf-8")
        self.commit_in(worktree, "work")
        self.assertIn("new.py", local.changed_paths(self.root, worktree, base=base))

    def test_several_commits_are_all_visible(self) -> None:
        worktree, base = self.worktree_for()
        for name in ("one.py", "two.py", "three.py"):
            (worktree / name).write_text("x\n", encoding="utf-8")
            self.commit_in(worktree, f"add {name}")
        changed = local.changed_paths(self.root, worktree, base=base)
        for name in ("one.py", "two.py", "three.py"):
            self.assertIn(name, changed)

    def test_a_repair_commit_on_top_stays_visible(self) -> None:
        worktree, base = self.worktree_for()
        (worktree / "first.py").write_text("x\n", encoding="utf-8")
        self.commit_in(worktree, "implementation")
        (worktree / "second.py").write_text("y\n", encoding="utf-8")
        self.commit_in(worktree, "repair")
        changed = local.changed_paths(self.root, worktree, base=base)
        self.assertIn("first.py", changed)
        self.assertIn("second.py", changed)

    def test_committed_and_uncommitted_work_are_both_visible(self) -> None:
        worktree, base = self.worktree_for()
        (worktree / "committed.py").write_text("x\n", encoding="utf-8")
        self.commit_in(worktree, "work")
        (worktree / "pending.py").write_text("y\n", encoding="utf-8")
        changed = local.changed_paths(self.root, worktree, base=base)
        self.assertIn("committed.py", changed)
        self.assertIn("pending.py", changed)

    def test_a_guarded_path_committed_by_the_worker_is_still_refused(self) -> None:
        """The security case: committing the change must not hide it."""
        worktree, base = self.worktree_for()
        (worktree / "ops" / "policy.json").write_text("{}", encoding="utf-8")
        self.commit_in(worktree, "quietly change governance")
        changed = local.changed_paths(self.root, worktree, base=base)
        self.assertEqual(governance.violations(changed), ["ops/policy.json"])

    def test_the_reviewer_sees_the_whole_task_delta(self) -> None:
        worktree, base = self.worktree_for()
        (worktree / "committed.py").write_text("committed change\n", encoding="utf-8")
        self.commit_in(worktree, "work")
        (worktree / "pending.py").write_text("pending change\n", encoding="utf-8")
        diff = local.diff_of(self.root, worktree, base=base)
        self.assertIn("committed change", diff)
        self.assertIn("pending change", diff)

    def test_the_baseline_does_not_move_forward_during_the_task(self) -> None:
        worktree, base = self.worktree_for()
        first = local.task_baseline(self.paths, 15, worktree=worktree)
        (worktree / "work.py").write_text("x\n", encoding="utf-8")
        self.commit_in(worktree, "work")
        second = local.task_baseline(self.paths, 15, worktree=worktree)
        self.assertEqual(first, second)
        self.assertEqual(first, base)

    def test_the_baseline_survives_a_restart(self) -> None:
        worktree, base = self.worktree_for()
        local.task_baseline(self.paths, 15, worktree=worktree)
        (worktree / "work.py").write_text("x\n", encoding="utf-8")
        self.commit_in(worktree, "work")
        reopened = localstate.LocalPaths(self.root)
        self.assertEqual(local.task_baseline(reopened, 15, worktree=worktree), base)

    def test_reading_the_dashboard_does_not_rewrite_the_baseline(self) -> None:
        worktree, base = self.worktree_for()
        local.task_baseline(self.paths, 15, worktree=worktree)
        (worktree / "work.py").write_text("x\n", encoding="utf-8")
        self.commit_in(worktree, "work")
        dashboard.snapshot(self.root, self.paths)
        self.assertEqual(local.task_baseline(self.paths, 15, worktree=worktree), base)

    def test_recovery_reports_the_baseline_it_kept(self) -> None:
        worktree, base = self.worktree_for()
        local.task_baseline(self.paths, 15, worktree=worktree)
        localstate.save_worker(
            self.paths, "15", {"task_id": 15, "worktree": str(worktree), "pid": 999_999}
        )
        report = local.recover(self.root, self.paths)
        self.assertEqual(report["workers"][0]["base_sha"], base)


class TestReadyForPrIsNotDispatchedAgain(RepoCase):
    def lease_in(self, state_name: str) -> None:
        localstate.write(
            self.paths.leases,
            {
                "leases": {
                    "15": {
                        "task_id": 15,
                        "owner": "local",
                        "branch": "b",
                        "state": state_name,
                        "heartbeat_at": localstate.now(),
                        "attempts": 1,
                    }
                }
            },
        )

    def test_a_task_waiting_for_its_pull_request_is_not_restarted(self) -> None:
        self.lease_in("ready_for_pr")
        with mock.patch.object(local, "run_worker") as worker:
            result = local.run_once(self.root, self.paths)
        worker.assert_not_called()
        self.assertFalse(result["dispatched"])
        self.assertIn("waiting for its pull request", result["reason"])

    def test_an_unreviewed_diagnostic_result_is_not_restarted_either(self) -> None:
        self.lease_in(local.UNREVIEWED)
        with mock.patch.object(local, "run_worker") as worker:
            result = local.run_once(self.root, self.paths)
        worker.assert_not_called()
        self.assertFalse(result["dispatched"])

    def test_the_settled_state_is_reported_rather_than_guessed(self) -> None:
        self.lease_in("ready_for_pr")
        tasks = local.load_leases(self.root, self.paths)
        self.assertEqual(local.settled_locally(tasks, 15), "ready_for_pr")
        self.assertEqual(local.settled_locally(tasks, 16), "")

    def test_a_blocked_task_is_not_treated_as_settled(self) -> None:
        """Blocked is the lease module's terminal state and keeps its meaning."""
        self.lease_in("blocked")
        tasks = local.load_leases(self.root, self.paths)
        self.assertEqual(local.settled_locally(tasks, 15), "")

    def test_a_restart_preserves_the_decision(self) -> None:
        self.lease_in("ready_for_pr")
        reopened = localstate.ensure(localstate.LocalPaths(self.root))
        tasks = local.load_leases(self.root, reopened)
        self.assertEqual(local.settled_locally(tasks, 15), "ready_for_pr")


class TestTheDashboardWritesNothing(RepoCase):
    def snapshot_tree(self) -> dict[str, bytes]:
        """Every file under the runtime directory, with its exact bytes."""
        out: dict[str, bytes] = {}
        for path in sorted(self.paths.dir.rglob("*")):
            if path.is_file():
                out[str(path.relative_to(self.paths.dir))] = path.read_bytes()
        return out

    def test_a_page_view_creates_no_runtime_state_at_all(self) -> None:
        """The first GET used to seed leases.json through the normal load
        path, so a documented read-only endpoint wrote to disk."""
        before = self.snapshot_tree()
        dashboard.snapshot(self.root, self.paths)
        self.assertEqual(self.snapshot_tree(), before)

    def test_rendering_the_page_creates_no_runtime_state(self) -> None:
        before = self.snapshot_tree()
        data = dashboard.snapshot(self.root, self.paths)
        dashboard.page(data, "")
        self.assertEqual(self.snapshot_tree(), before)

    def test_the_lease_file_is_not_created_by_a_read(self) -> None:
        self.paths.leases.unlink(missing_ok=True)
        dashboard.snapshot(self.root, self.paths)
        self.assertFalse(self.paths.leases.exists())

    def test_the_read_path_still_reports_the_tracked_baseline(self) -> None:
        (self.root / "ops" / "state" / "tasks.json").write_text(
            json.dumps({"leases": {"7": {"task_id": 7, "state": "review"}}}),
            encoding="utf-8",
        )
        self.paths.leases.unlink(missing_ok=True)
        tasks = local.read_leases(self.root, self.paths)
        self.assertIn("7", tasks["leases"])
        self.assertFalse(self.paths.leases.exists())


class TestGatedVerificationRunsTheWorktree(RepoCase):
    def test_the_command_names_the_worktree_copy_of_the_script(self) -> None:
        """check.ps1 moves to the parent of its own location, so running the
        repository's copy verified the coordinator's tree, not the branch."""
        worktree, _ = self.worktree_for()
        seen: list[list[str]] = []

        def runner(command, **kwargs):  # type: ignore[no-untyped-def]
            seen.append(command)
            return mock.Mock(returncode=0, stdout="", stderr="")

        local.verify(
            self.root,
            self.paths,
            worktree,
            kind="gated",
            runner=runner,
            uv=Path("uv"),
        )
        script = seen[0][-1]
        self.assertIn(str(worktree), script)
        self.assertNotIn(str(self.root / "scripts"), script)

    def test_the_checks_run_with_the_worktree_as_the_working_directory(self) -> None:
        worktree, _ = self.worktree_for()
        seen: dict[str, Any] = {}

        def runner(command, **kwargs):  # type: ignore[no-untyped-def]
            seen.update(kwargs)
            return mock.Mock(returncode=0, stdout="", stderr="")

        local.verify(self.root, self.paths, worktree, runner=runner, uv=Path("uv"))
        self.assertEqual(seen["cwd"], str(worktree))

    def test_the_version_under_verification_is_the_worktree_version(self) -> None:
        """A difference that exists only in the worktree must be the one the
        checks see."""
        worktree, _ = self.worktree_for()
        (worktree / "marker.txt").write_text("worktree version\n", encoding="utf-8")
        observed: list[str] = []

        def runner(command, **kwargs):  # type: ignore[no-untyped-def]
            marker = Path(kwargs["cwd"]) / "marker.txt"
            observed.append(
                marker.read_text(encoding="utf-8").strip()
                if marker.exists()
                else "absent"
            )
            return mock.Mock(returncode=0, stdout="", stderr="")

        local.verify(self.root, self.paths, worktree, runner=runner, uv=Path("uv"))
        self.assertEqual(observed[0], "worktree version")
        self.assertFalse((self.root / "marker.txt").exists())


class TestTheRestOfTheReviewFindings(RepoCase):
    """Smaller defects from the same review, each verified before fixing."""

    def test_a_worktree_root_inside_the_repository_is_refused(self) -> None:
        """It would put an unattended worker in the coordinator's own tree."""
        with self.assertRaises(ValueError):
            local.worktree_root(self.root, {"worktree_root": str(self.root / "wt")})

    def test_the_repository_itself_is_refused_as_a_worktree_root(self) -> None:
        with self.assertRaises(ValueError):
            local.worktree_root(self.root, {"worktree_root": str(self.root)})

    def test_a_sibling_directory_is_accepted(self) -> None:
        sibling = self.root.parent / "agents"
        self.assertEqual(
            local.worktree_root(self.root, {"worktree_root": str(sibling)}), sibling
        )

    def test_an_unrecognised_verdict_is_unreadable_not_a_pass(self) -> None:
        """`{}` and a typo both used to read as a clean review."""
        self.assertEqual(local.parse_findings("{}")["verdict"], "unreadable")
        self.assertEqual(
            local.parse_findings('{"verdict": "pas", "findings": []}')["verdict"],
            "unreadable",
        )
        self.assertEqual(
            local.parse_findings('{"verdict": "approved"}')["verdict"], "unreadable"
        )

    def test_the_two_documented_verdicts_are_still_accepted(self) -> None:
        self.assertEqual(
            local.parse_findings('{"verdict": "pass", "findings": []}')["verdict"],
            "pass",
        )
        self.assertEqual(
            local.parse_findings('{"verdict": "changes_requested"}')["verdict"],
            "changes_requested",
        )

    def test_a_reviewer_that_failed_blocks_rather_than_being_parsed(self) -> None:
        """A crashed reviewer can still have printed something pass-shaped."""
        clean = json.dumps({"verdict": "pass", "summary": "fine", "findings": []})

        def worker(root, paths, **kwargs):  # type: ignore[no-untyped-def]
            if kwargs["role"] == "review":
                return {
                    "ok": False,
                    "outcome": "timeout",
                    "run_id": "r",
                    "usage": {},
                    "cost_usd": 0.0,
                    "last_action": clean,
                }
            (kwargs["worktree"] / "work.py").write_text("x\n", encoding="utf-8")
            return {
                "ok": True,
                "outcome": "completed",
                "run_id": "i",
                "usage": {},
                "cost_usd": 0.0,
                "last_action": "done",
            }

        with mock.patch.object(local, "run_worker", side_effect=worker):
            with mock.patch.object(
                local, "verify", return_value={"ok": True, "steps": [], "failed": None}
            ):
                result = local.run_once(self.root, self.paths)
        self.assertEqual(result["outcome"], "blocked")
        self.assertIn("did not complete", result["detail"])

    def test_an_abandoned_lease_is_reclaimed_on_the_next_run(self) -> None:
        """A run that ended mid-repair left the task unavailable for as long
        as the lease took to go stale."""
        localstate.write(
            self.paths.leases,
            {
                "leases": {
                    "15": {
                        "task_id": 15,
                        "owner": "local-999999",
                        "branch": "b",
                        "state": "repairing",
                        "heartbeat_at": localstate.now(),
                        "attempts": 1,
                        "pid": 999_999,
                        "image": "claude.exe",
                    }
                }
            },
        )
        tasks = local.load_leases(self.root, self.paths)
        policy = json.loads(
            (self.root / "ops" / "policy.json").read_text(encoding="utf-8")
        )
        self.assertFalse(leases.is_stale(tasks["leases"]["15"], policy))
        self.assertEqual(local.reclaim_abandoned(self.paths, tasks, policy), [15])
        self.assertTrue(leases.is_stale(tasks["leases"]["15"], policy))

    def test_a_live_owner_keeps_its_lease(self) -> None:
        localstate.write(
            self.paths.leases,
            {
                "leases": {
                    "15": {
                        "task_id": 15,
                        "owner": "local",
                        "branch": "b",
                        "state": "implementing",
                        "heartbeat_at": localstate.now(),
                        "attempts": 1,
                        "pid": os.getpid(),
                    }
                }
            },
        )
        tasks = local.load_leases(self.root, self.paths)
        policy = json.loads(
            (self.root / "ops" / "policy.json").read_text(encoding="utf-8")
        )
        with mock.patch.object(localstate, "process_alive", return_value=True):
            self.assertEqual(local.reclaim_abandoned(self.paths, tasks, policy), [])

    def test_the_worker_pid_reaches_the_lease(self) -> None:
        """The stale-lease check asks whether the previous owner is running,
        and a lease with no pid answers 'gone' for a live worker."""
        source = (REPO_ROOT / "services" / "agentops" / "local.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('lease["pid"] = pid', source)


class TestDoctorAndEvaluate(RepoCase):
    def run_cli(self, *args: str) -> dict[str, Any]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["--root", str(self.root), *args])
        self.assertEqual(code, 0, out.getvalue())
        payload: dict[str, Any] = json.loads(out.getvalue())
        return payload

    def test_doctor_is_not_ok_when_the_selected_provider_cannot_run(self) -> None:
        config = localstate.load_config(self.paths)
        config["provider"] = "openrouter"
        localstate.save_config(self.paths, config)
        with mock.patch.dict(os.environ, {}, clear=True):
            payload = self.run_cli("doctor")
        self.assertEqual(payload["provider"]["status"], "AVAILABLE_LATER")
        self.assertFalse(payload["ok"])

    def test_doctor_is_ok_when_the_selected_provider_can_run(self) -> None:
        payload = self.run_cli("doctor")
        self.assertEqual(payload["provider"]["status"], "AVAILABLE")

    def test_an_anthropic_model_id_is_not_sent_to_the_openrouter_harness(self) -> None:
        """Namespaced ids are not an OpenRouter-only shape, so inferring the
        lane from a slash routed Anthropic models through OpenCode."""
        seen: dict[str, Any] = {}

        def evaluate(root, paths, model, **kwargs):  # type: ignore[no-untyped-def]
            seen["model"] = model
            seen["lane"] = kwargs.get("lane")
            return {"model": model, "lane": kwargs.get("lane")}

        store = approvals.load(self.paths)
        approvals.set_state(
            self.paths, store, "anthropic/claude-sonnet-5", approvals.APPROVED
        )
        with mock.patch.object(local, "evaluate_model", side_effect=evaluate):
            self.run_cli("evaluate", "anthropic/claude-sonnet-5")
        self.assertEqual(seen["lane"], "claude_subscription")


class TestOnlyOneCoordinatorMayClaim(RepoCase):
    def test_a_second_coordinator_is_refused_while_the_first_decides(self) -> None:
        """Read, claim and write is not atomic across processes on its own:
        both could see no lease and both start a worker on the same branch."""
        from services.agentops import toolchain

        with toolchain.schedule_lock(self.paths, owner="first"):
            with mock.patch.object(local, "run_worker") as worker:
                result = local.run_once(self.root, self.paths)
        worker.assert_not_called()
        self.assertFalse(result["dispatched"])
        self.assertIn("another coordinator is deciding", result["reason"])

    def test_scheduling_does_not_wait_behind_a_gated_verification(self) -> None:
        """They are separate locks: a gated run holds the infrastructure lock
        for minutes, and scheduling must not queue behind it."""
        from services.agentops import toolchain

        with toolchain.infra_lock(self.paths, owner="verifier"):
            with toolchain.schedule_lock(self.paths, owner="coordinator") as held:
                self.assertEqual(held["owner"], "coordinator")

    def test_the_lock_is_released_after_the_decision(self) -> None:
        from services.agentops import toolchain

        with mock.patch.object(local, "run_worker") as worker:
            worker.return_value = {
                "ok": False,
                "outcome": "failed",
                "run_id": "r",
                "usage": {},
                "cost_usd": 0.0,
                "last_action": "",
            }
            local.run_once(self.root, self.paths)
        with toolchain.schedule_lock(self.paths, owner="next") as held:
            self.assertFalse(held["recovered"])


if __name__ == "__main__":
    unittest.main()
