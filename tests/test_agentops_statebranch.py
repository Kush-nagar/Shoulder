"""Runtime state must not need a hole in the default branch's protection.

The system used to push leases, provider health, spend and progress straight to
the default branch. That only works if the branch is unprotected or grants a
bypass actor, and on a personal repository there is no GitHub Actions bypass to
grant -- so the design could not run at all once protection was on.

These cover the replacement: an orphan `agentops-state` branch holding
`ops/state` and nothing else, and the guarantee that product code still has to
go through a reviewed pull request to reach main.
"""

from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path
from typing import Any

from agentops_fixtures import REPO_ROOT, policy

from services.agentops import state, statebranch

WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
AGENTOPS_WORKFLOWS = sorted(WORKFLOW_DIR.glob("agentops-*.yml"))
PRODUCT_DIRS = ("services/api", "apps/web", "migrations", "packages", "scripts")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestNothingPushesTheProtectedBranch(unittest.TestCase):
    """The property the whole redesign exists to establish."""

    def test_no_workflow_pushes_to_the_default_branch(self) -> None:
        pushes = re.compile(r"git(?:_auth)?\s+push[^\n]*HEAD:")
        for path in AGENTOPS_WORKFLOWS:
            with self.subTest(path.name):
                for line in read(path).splitlines():
                    if pushes.search(line):
                        self.fail(f"{path.name} still pushes a ref directly: {line!r}")

    def test_no_workflow_names_the_default_branch_as_a_push_target(self) -> None:
        for path in AGENTOPS_WORKFLOWS:
            text = read(path)
            with self.subTest(path.name):
                self.assertNotIn("HEAD:main", text)
                self.assertNotIn("HEAD:$DEFAULT_BRANCH", text)

    def test_every_state_writer_uses_the_state_branch(self) -> None:
        """A workflow that mutates the ledger must also be the one that writes
        it somewhere durable; recording only in the runner records nothing."""
        for path in AGENTOPS_WORKFLOWS:
            text = read(path)
            mutates = any(
                marker in text
                for marker in (
                    "cli attach",
                    "cli dispatch",
                    "cli repair",
                    "cli health --lane",
                    "cli spend",
                    "cli merge-verdicts",
                    "agentops.watchdog --repo",
                    "agentops.reconcile --repo",
                )
            )
            if not mutates:
                continue
            with self.subTest(path.name):
                self.assertIn("cli state-push", text)

    def test_every_state_reader_pulls_before_reading(self) -> None:
        """The copies committed on the default branch are a seed. Reading them
        as if they were live would plan against a stale ledger."""
        for path in AGENTOPS_WORKFLOWS:
            text = read(path)
            if "cli state-push" not in text and "ops/state/tasks.json" not in text:
                continue
            with self.subTest(path.name):
                self.assertIn("cli state-pull", text)

    def test_product_code_still_needs_a_reviewed_pull_request(self) -> None:
        """The point of moving the ledger was to keep this true, not to widen
        what automation may write. Nothing may push product paths anywhere."""
        for path in AGENTOPS_WORKFLOWS:
            text = read(path)
            for directory in PRODUCT_DIRS:
                with self.subTest(f"{path.name}:{directory}"):
                    self.assertNotIn(f"git add {directory}", text)

    def test_the_worker_pushes_only_its_own_task_branch(self) -> None:
        text = read(WORKFLOW_DIR / "agentops-worker.yml")
        self.assertIn('git push --force-with-lease origin "$BRANCH"', text)
        # And a reserved name is refused before it gets there.
        self.assertIn("refusing to work on the reserved branch", text)


class TestTheStateBranchHoldsOnlyState(unittest.TestCase):
    """Structural, not a rule someone has to remember."""

    def test_the_commit_tree_is_built_from_an_empty_index(self) -> None:
        """Nothing else in the worktree can reach the tree this builds, which
        is what stops a task branch's content riding along."""
        source = read(Path(statebranch.__file__))
        self.assertIn('"read-tree", "--empty"', source)
        self.assertIn('"add", "--all", "--", TRACKED', source)
        self.assertIn("GIT_INDEX_FILE", source)

    def test_it_tracks_the_state_directory_and_nothing_wider(self) -> None:
        self.assertEqual(statebranch.TRACKED, "ops/state")
        self.assertEqual(statebranch.BRANCH, "agentops-state")

    def test_the_real_branch_carries_no_product_code(self) -> None:
        """Checked against the branch this repository actually has, when it has
        one. A stray path here would mean product code reached main without a
        pull request."""
        paths = statebranch.contents(REPO_ROOT)
        if not paths:
            self.skipTest("the state branch does not exist in this checkout yet")
        for entry in paths:
            with self.subTest(entry):
                self.assertTrue(entry.startswith("ops/state/"), entry)

    def test_a_push_never_targets_the_default_branch(self) -> None:
        source = read(Path(statebranch.__file__))
        self.assertIn('f"{commit}:refs/heads/{BRANCH}"', source)
        self.assertNotIn("refs/heads/main", source)

    def test_it_carries_its_own_commit_identity(self) -> None:
        """A runner with no `git config` set fails commit-tree outright, and
        that failure would look like a lost race rather than a missing
        setting."""
        self.assertIn("GIT_COMMITTER_NAME", statebranch.IDENTITY)
        self.assertIn("GIT_AUTHOR_EMAIL", statebranch.IDENTITY)

    def test_a_losing_race_reapplies_only_this_runs_files(self) -> None:
        """Files this run did not touch keep the other writer's version, which
        is what a successful rebase used to do."""
        source = read(Path(statebranch.__file__))
        self.assertIn("def changed_files", source)
        self.assertIn("for name, blob in mine.items()", source)


class TestTheGateCannotBeOpenedByTheSystem(unittest.TestCase):
    """The ledger is now on a branch the orchestrator writes without review.

    A gate stored there would be a gate the system could open for itself, and
    this one is what stands between autonomy and the machine-learning phases
    AGENTS.md rule 5 forbids.
    """

    def test_the_gate_lives_in_policy_on_the_protected_branch(self) -> None:
        self.assertIn("real_use_gate", policy()["gates"])

    def test_policy_is_not_written_by_any_state_write(self) -> None:
        """`ops/policy.json` sits outside ops/state, so the tree a state push
        builds structurally cannot contain it."""
        self.assertFalse(
            str(state.Paths(REPO_ROOT).policy)
            .replace("\\", "/")
            .endswith("ops/state/policy.json")
        )
        paths = statebranch.contents(REPO_ROOT)
        self.assertNotIn("ops/policy.json", paths)

    def test_a_ledger_claiming_the_gate_is_open_does_not_open_it(self) -> None:
        """The file automation can write must not be able to grant this."""
        settings = policy()
        settings["gates"]["real_use_gate"] = False
        forged = {"gates": {"real_use_gate": True}}
        self.assertFalse(state.gate_passed(settings, forged))

    def test_policy_alone_can_grant_it(self) -> None:
        settings = policy()
        settings["gates"]["real_use_gate"] = True
        self.assertTrue(state.gate_passed(settings, {}))

    def test_a_stale_ledger_may_still_refuse_it(self) -> None:
        """Refusing is safe in a way granting is not, so a pre-migration ledger
        that says the gate is shut is still honoured."""
        settings = policy()
        settings["gates"]["real_use_gate"] = True
        self.assertFalse(
            state.gate_passed(settings, {"gates": {"real_use_gate": False}})
        )

    def test_phase_d_stays_shut_whatever_the_ledger_says(self) -> None:
        from services.agentops import coordinator

        ctx = coordinator.load_context(REPO_ROOT)
        # Pretend the ledger was tampered with in every way that would help.
        ctx.progress = {
            "completed_tasks": list(range(1, 23)),
            "gates": {"real_use_gate": True},
        }
        gated = [
            c
            for c in coordinator.candidates(ctx)
            if "Phase D" in c.task.phase or "Phase E" in c.task.phase
        ]
        self.assertTrue(gated)
        for candidate in gated:
            with self.subTest(candidate.task.id):
                self.assertFalse(candidate.eligible, candidate.reasons)


class TestTheLedgerNeverRidesAProductPullRequest(unittest.TestCase):
    """`state-pull` writes the live ledger into the worktree, and the worker
    later stages everything on its task branch."""

    def test_the_worker_restores_the_ledger_before_staging(self) -> None:
        """Otherwise leases, spend and provider health are committed into a
        product pull request, a reviewer is asked to approve them, and merging
        copies them onto main."""
        text = read(WORKFLOW_DIR / "agentops-worker.yml")
        push = text.split("- name: Push the branch and open a pull request", 1)[1]
        # Executable lines only. Searching the raw text matched the comment
        # above the fix, which explains the hazard by naming `git add -A`.
        commands = [
            line.strip()
            for line in push.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        restore = commands.index("git checkout HEAD -- ops/state 2>/dev/null || true")
        stage = commands.index("git add -A")
        self.assertLess(restore, stage)
        self.assertIn("git reset -q -- ops/state 2>/dev/null || true", commands)

    def test_the_change_check_ignores_the_ledger(self) -> None:
        text = read(WORKFLOW_DIR / "agentops-worker.yml")
        self.assertIn("':!ops/state'", text)


class TestMigrationFromTheOldLayout(unittest.TestCase):
    def test_the_seed_files_are_still_committed(self) -> None:
        """Before the branch exists they are what `pull` falls back to, which
        is what makes a fresh repository and a migrating one take one path."""
        for name in ("tasks", "providers", "budget", "progress", "models"):
            with self.subTest(name):
                self.assertTrue((REPO_ROOT / "ops" / "state" / f"{name}.json").exists())

    def test_pull_falls_back_to_the_seed_when_the_branch_is_absent(self) -> None:
        from unittest import mock

        with mock.patch.object(statebranch, "remote_ref", return_value=None):
            result = statebranch.pull(REPO_ROOT)
        self.assertEqual(result["source"], "seed")
        self.assertFalse(result["existed"])

    def test_the_seed_says_it_is_a_seed(self) -> None:
        """Two files that look equally authoritative is how a stale one gets
        trusted."""
        readme = read(REPO_ROOT / "ops" / "README.md")
        self.assertIn("agentops-state", readme)

    def test_the_state_files_parse_as_the_shapes_the_system_expects(self) -> None:
        paths = state.Paths(REPO_ROOT)
        for path, key in (
            (paths.tasks, "leases"),
            (paths.providers, "lanes"),
            (paths.progress, "completed_tasks"),
            (paths.models, "models"),
        ):
            with self.subTest(path.name):
                loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
                self.assertIn(key, loaded)


class TestStateBranchAgainstRealGit(unittest.TestCase):
    """Exercised against a throwaway repository, not the real remote."""

    def setUp(self) -> None:
        import shutil
        import tempfile

        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.remote = self.tmp / "remote.git"
        self.work = self.tmp / "work"
        self._git(self.tmp, "init", "--bare", "-b", "main", str(self.remote))
        self._git(self.tmp, "clone", str(self.remote), str(self.work))
        (self.work / "ops" / "state").mkdir(parents=True)
        (self.work / "ops" / "state" / "tasks.json").write_text(
            '{"leases": {}}\n', encoding="utf-8"
        )
        (self.work / "product.py").write_text("x = 1\n", encoding="utf-8")
        self._git(self.work, "add", "-A")
        self._commit(self.work, "seed")
        self._git(self.work, "push", "origin", "main")

    def _git(self, cwd: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
            errors="replace",
        )
        return result.stdout.strip()

    def _commit(self, cwd: Path, message: str) -> None:
        subprocess.run(
            ["git", "commit", "-m", message],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
            errors="replace",
            env={
                **statebranch.IDENTITY,
                "PATH": __import__("os").environ.get("PATH", ""),
                "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", ""),
            },
        )

    def test_a_push_creates_a_branch_holding_only_state(self) -> None:
        result = statebranch.push(self.work, "first")
        self.assertTrue(result["pushed"], result)
        self.assertEqual(statebranch.contents(self.work), ["ops/state/tasks.json"])

    def test_product_files_never_reach_that_branch(self) -> None:
        """product.py is committed in this worktree and must not appear."""
        statebranch.push(self.work, "first")
        self.assertNotIn("product.py", statebranch.contents(self.work))

    def test_a_second_push_carries_the_change_forward(self) -> None:
        statebranch.push(self.work, "first")
        (self.work / "ops" / "state" / "tasks.json").write_text(
            '{"leases": {"15": {"task_id": 15}}}\n', encoding="utf-8"
        )
        result = statebranch.push(self.work, "second")
        self.assertTrue(result["pushed"], result)

        statebranch.pull(self.work)
        loaded = json.loads(
            (self.work / "ops" / "state" / "tasks.json").read_text(encoding="utf-8")
        )
        self.assertIn("15", loaded["leases"])

    def test_an_unchanged_push_is_a_no_op(self) -> None:
        statebranch.push(self.work, "first")
        result = statebranch.push(self.work, "again")
        self.assertTrue(result["pushed"])
        self.assertFalse(result["changed"])

    def test_a_losing_race_keeps_the_other_writers_file(self) -> None:
        """The whole point of re-applying per file rather than overwriting."""
        import shutil

        statebranch.push(self.work, "first")

        other = self.tmp / "other"
        shutil.copytree(self.work, other)
        statebranch.pull(other)
        (other / "ops" / "state" / "providers.json").write_text(
            '{"lanes": {"claude_subscription": {"status": "AVAILABLE"}}}\n',
            encoding="utf-8",
        )
        self.assertTrue(statebranch.push(other, "theirs")["pushed"])

        # This writer started from the older branch and changed a different
        # file. Its push loses the race, re-applies, and both survive.
        (self.work / "ops" / "state" / "tasks.json").write_text(
            '{"leases": {"15": {"task_id": 15}}}\n', encoding="utf-8"
        )
        result = statebranch.push(self.work, "mine")
        self.assertTrue(result["pushed"], result)

        statebranch.pull(self.work)
        tasks = json.loads(
            (self.work / "ops" / "state" / "tasks.json").read_text(encoding="utf-8")
        )
        providers = json.loads(
            (self.work / "ops" / "state" / "providers.json").read_text(encoding="utf-8")
        )
        self.assertIn("15", tasks["leases"])
        self.assertIn("claude_subscription", providers["lanes"])

    def test_the_default_branch_is_untouched_throughout(self) -> None:
        before = self._git(self.work, "rev-parse", "origin/main")
        statebranch.push(self.work, "first")
        (self.work / "ops" / "state" / "tasks.json").write_text(
            '{"leases": {"1": {}}}\n', encoding="utf-8"
        )
        statebranch.push(self.work, "second")
        self._git(self.work, "fetch", "origin", "main")
        self.assertEqual(before, self._git(self.work, "rev-parse", "origin/main"))


if __name__ == "__main__":
    unittest.main()
