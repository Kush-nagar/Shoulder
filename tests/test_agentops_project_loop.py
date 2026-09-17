"""The backlog, worked to the end, without a person between the stages.

Each stage already existed and was already tested. What is new is the join, and
a join is exactly where the interesting failures live: a merge that nobody
reconciled, a task selected while its prerequisite is still open, a gate that
answered "I could not tell" being read as "clean", a blocker that tidied away
the worktree it was blocking on.

So these tests drive the whole loop with a scripted GitHub and a scripted
worker, and assert what it did -- including the things it must refuse to do.
`gh` and `git` are reached through two functions in the module, so replacing
those replaces the whole outside world; no test here touches a network, and
none can make a paid call.
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

from services.agentops import (
    brief,
    delegate,
    local,
    localstate,
    project,
    reconcile,
    review,
    state,
)


def completed(returncode: int = 0, stdout: str = "") -> Any:
    return subprocess.CompletedProcess(
        args=["fake"], returncode=returncode, stdout=stdout, stderr=""
    )


def rollup(*checks: tuple[str, str]) -> str:
    return json.dumps(
        {
            "statusCheckRollup": [
                {"name": name, "bucket": bucket, "conclusion": bucket}
                for name, bucket in checks
            ],
            "mergeStateStatus": "CLEAN",
            "headRefOid": "deadbeef",
        }
    )


class FakeGitHub:
    """Every `gh` call the loop makes, answered from a script.

    It records the argument vectors as well, because several of the rules this
    module has to obey are about commands it must never issue.
    """

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.pulls: dict[str, int] = {}
        self.next_number = 101
        self.ci: list[str] = [rollup(("check", "pass"))]
        self.merged: list[int] = []
        self.merge_refusal = ""

    def __call__(self, args: list[str], *, repo: str | None = None) -> Any:
        self.calls.append(list(args))
        if args[:2] == ["repo", "view"]:
            return completed(stdout=json.dumps({"nameWithOwner": "owner/repo"}))
        if args[:2] == ["pr", "list"]:
            branch = args[args.index("--head") + 1]
            number = self.pulls.get(branch)
            return completed(stdout=json.dumps([{"number": number}] if number else []))
        if args[:2] == ["pr", "create"]:
            branch = args[args.index("--head") + 1]
            number = self.pulls.setdefault(branch, self.next_number)
            self.next_number += 1
            return completed(stdout=f"https://github.com/owner/repo/pull/{number}\n")
        if args[:2] == ["pr", "view"]:
            body = self.ci[0] if len(self.ci) == 1 else self.ci.pop(0)
            return completed(stdout=body)
        if args[:2] == ["pr", "merge"]:
            if self.merge_refusal:
                return completed(returncode=1, stdout=self.merge_refusal)
            self.merged.append(int(args[2]))
            return completed(stdout="merged")
        return completed(stdout="{}")

    def issued(self, *needles: str) -> bool:
        return any(
            all(needle in " ".join(call) for needle in needles) for call in self.calls
        )


class ProjectCase(unittest.TestCase):
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
        local.enable_local(self.paths, by="test")

        self.gh = FakeGitHub()
        self.git_calls: list[list[str]] = []
        self.removed: list[str] = []
        self.task_of_branch: dict[str, int] = {}
        self.reconciles: set[int] = set()
        self.dirty: list[str] = []
        self.reviews: list[dict[str, Any]] = [{"verdict": "pass", "findings": []}]
        self.repairs: list[dict[str, Any]] = []
        self.dispatched: list[dict[str, Any]] = []

    # -- the scripted outside world -------------------------------------

    def fake_git(self, root: Path, args: list[str]) -> Any:
        self.git_calls.append(list(args))
        if args[:1] == ["status"]:
            return completed(stdout="".join(f" M {p}\n" for p in self.dirty))
        if args[:1] == ["rev-parse"]:
            return completed(stdout="agentops/test\n")
        return completed()

    def fake_verdict(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return self.reviews[0] if len(self.reviews) == 1 else self.reviews.pop(0)

    def fake_run_once(self, root: Path, paths: Any, **kwargs: Any) -> dict[str, Any]:
        result = self.dispatched.pop(0)
        return result

    def fake_reconcile(self, root: Path, *, repo: str | None = None) -> dict[str, Any]:
        """Complete the tasks whose pull request merged, like the real one."""
        progress = state.read_json(state.Paths(root).progress, {"completed_tasks": []})
        done = set(state.completed_tasks(progress))
        for branch, number in self.gh.pulls.items():
            task_id = self.task_of_branch.get(branch)
            if task_id is not None and number in self.gh.merged:
                if task_id in self.reconciles:
                    done.add(task_id)
        progress["completed_tasks"] = sorted(done)
        state.write_json(state.Paths(root).progress, progress)
        return {"completed": []}

    def ready(self, task_id: int, branch: str = "block-x-t1-fixture") -> dict[str, Any]:
        worktree = Path(self.tmp.name) / "agents" / branch
        worktree.mkdir(parents=True, exist_ok=True)
        self.task_of_branch[branch] = task_id
        return {
            "dispatched": True,
            "task_id": task_id,
            "branch": branch,
            "worktree": str(worktree),
            "outcome": "ready_for_pr",
            "detail": "",
        }

    def drive(self, **kwargs: Any) -> dict[str, Any]:
        """Run the loop against the scripted world."""
        with (
            mock.patch.object(project, "_gh", self.gh),
            mock.patch.object(delegate, "_gh", self.gh),
            mock.patch.object(project, "_git", self.fake_git),
            mock.patch.object(review, "verdict", self.fake_verdict),
            mock.patch.object(local, "run_once", self.fake_run_once),
            mock.patch.object(reconcile, "reconcile", self.fake_reconcile),
            mock.patch.object(local, "remove_worktree", self.record_removal),
            mock.patch.object(
                local, "changed_paths", lambda *a, **k: ["services/api/x.py"]
            ),
            mock.patch.object(local, "task_baseline", lambda *a, **k: "base0"),
            mock.patch.object(brief, "render", lambda *a, **k: "the brief"),
            mock.patch.object(project, "repair_in_worktree", self.record_repair),
            mock.patch("time.sleep", lambda _s: None),
        ):
            defaults: dict[str, Any] = {
                "repo": "owner/repo",
                "verification": "fast",
                "poll_seconds": 0,
                "gate_timeout_seconds": 5,
            }
            defaults.update(kwargs)
            return project.run_project(self.root, self.paths, **defaults)

    def record_repair(self, *_args: Any, **kwargs: Any) -> dict[str, Any]:
        self.repairs.append(kwargs)
        return {"repaired": True}

    def record_removal(self, _root: Path, path: Path, **_kwargs: Any) -> dict[str, Any]:
        self.removed.append(str(path))
        return {"removed": True}


class TestOneTaskEndToEnd(ProjectCase):
    def setUp(self) -> None:
        super().setUp()
        self.dispatched = [self.ready(15)]
        self.reconciles = {15}

    def test_a_clean_task_reaches_a_merged_pull_request(self) -> None:
        result = self.drive(max_tasks=1)
        self.assertEqual(result["status"], project.RUNNING, result)
        self.assertEqual(len(result["merged"]), 1)
        self.assertTrue(result["merged"][0]["merged"])

    def test_ready_for_pr_is_pushed_before_the_pull_request_is_opened(self) -> None:
        self.drive(max_tasks=1)
        pushes = [c for c in self.git_calls if c[:1] == ["push"]]
        self.assertTrue(pushes, self.git_calls)
        self.assertTrue(self.gh.issued("pr", "create"))

    def test_the_pull_request_is_not_a_draft(self) -> None:
        """A draft cannot be merged, and this branch is already reviewed."""
        self.drive(max_tasks=1)
        create = next(c for c in self.gh.calls if c[:2] == ["pr", "create"])
        self.assertNotIn("--draft", create)

    def test_the_merge_is_a_squash_with_no_administrative_override(self) -> None:
        self.drive(max_tasks=1)
        merge = next(c for c in self.gh.calls if c[:2] == ["pr", "merge"])
        self.assertIn("--squash", merge)
        self.assertNotIn("--admin", merge)

    def test_the_merged_task_is_reconciled_before_the_next_is_chosen(self) -> None:
        self.drive(max_tasks=1)
        progress = state.read_json(state.Paths(self.root).progress)
        self.assertIn(15, state.completed_tasks(progress))

    def test_the_finished_worktree_is_removed(self) -> None:
        self.drive(max_tasks=1)
        self.assertEqual(len(self.removed), 1)


class TestRepairLoops(ProjectCase):
    def setUp(self) -> None:
        super().setUp()
        self.dispatched = [self.ready(15)]
        self.reconciles = {15}

    def test_a_failing_check_is_repaired_pushed_and_rechecked(self) -> None:
        self.gh.ci = [
            rollup(("quality-gate", "fail")),
            rollup(("quality-gate", "pass")),
        ]
        result = self.drive(max_tasks=1)
        self.assertEqual(len(self.repairs), 1)
        self.assertEqual(self.repairs[0]["findings"][0]["severity"], "blocker")
        self.assertIn("quality-gate", self.repairs[0]["findings"][0]["requirement"])
        self.assertTrue(result["merged"])

    def test_a_pending_check_is_waited_on_rather_than_merged(self) -> None:
        self.gh.ci = [rollup(("quality-gate", "pending")), rollup(("q", "pass"))]
        result = self.drive(max_tasks=1)
        self.assertTrue(result["merged"], result)

    def test_a_review_finding_is_repaired_and_the_review_asked_again(self) -> None:
        self.reviews = [
            {
                "verdict": "changes_requested",
                "findings": [{"path": "a.py", "line": 3, "summary": "fix this"}],
            },
            {"verdict": "pass", "findings": []},
        ]
        result = self.drive(max_tasks=1)
        self.assertEqual(len(self.repairs), 1)
        self.assertEqual(self.repairs[0]["findings"][0]["file"], "a.py")
        self.assertTrue(result["merged"])

    def test_checks_that_never_go_green_stop_with_the_exact_findings(self) -> None:
        self.gh.ci = [rollup(("quality-gate", "fail"))]
        result = self.drive(max_tasks=1)
        self.assertEqual(result["status"], project.BLOCKED_HUMAN, result)
        self.assertEqual(result["findings"][0]["name"], "quality-gate")

    def test_a_review_that_never_clears_stops_with_its_findings(self) -> None:
        self.reviews = [
            {
                "verdict": "changes_requested",
                "findings": [{"path": "a.py", "line": 1, "summary": "still wrong"}],
            }
        ]
        result = self.drive(max_tasks=1)
        self.assertEqual(result["status"], project.BLOCKED_HUMAN)
        self.assertTrue(result["findings"])


class TestRefusals(ProjectCase):
    def setUp(self) -> None:
        super().setUp()
        self.dispatched = [self.ready(15)]
        self.reconciles = {15}

    def test_unexplained_local_changes_stop_before_anything_is_pushed(self) -> None:
        self.dirty = ["services/api/half-done.py"]
        result = self.drive(max_tasks=1)
        self.assertEqual(result["status"], project.BLOCKED_LOCAL_CHECKOUT)
        self.assertFalse([c for c in self.git_calls if c[:1] == ["push"]])
        self.assertFalse(self.gh.merged)

    def test_nothing_resets_stashes_or_force_pushes(self) -> None:
        self.drive(max_tasks=1)
        flat = [" ".join(call) for call in self.git_calls]
        for forbidden in ("reset", "stash", "--force", "-f "):
            self.assertFalse(
                [line for line in flat if forbidden in line], f"{forbidden}: {flat}"
            )

    def test_an_unreadable_check_state_is_never_read_as_clean(self) -> None:
        self.gh.ci = ["not json at all"]
        result = self.drive(max_tasks=1)
        self.assertEqual(result["status"], project.BLOCKED_HUMAN)
        self.assertFalse(self.gh.merged)

    def test_a_refused_merge_is_reported_not_retried_with_admin(self) -> None:
        self.gh.merge_refusal = "Protected branch update failed"
        result = self.drive(max_tasks=1)
        self.assertEqual(result["status"], project.BLOCKED_HUMAN)
        self.assertNotIn("--admin", " ".join(sum(self.gh.calls, [])))

    def test_a_merge_that_is_not_reconciled_stops_rather_than_redoing_it(self) -> None:
        self.reconciles = set()
        result = self.drive(max_tasks=1)
        self.assertEqual(result["status"], project.BLOCKED_HUMAN)
        self.assertIn("not reconciled", result["detail"])

    def test_a_provider_stall_is_named_as_waiting_not_as_a_human_blocker(self) -> None:
        self.dispatched = [
            {
                "dispatched": True,
                "task_id": 15,
                "branch": "b",
                "worktree": str(self.root),
                "outcome": "blocked",
                "detail": "BLOCKED_WAITING_PROVIDER: claude_subscription is out",
            }
        ]
        result = self.drive(max_tasks=1)
        self.assertEqual(result["status"], project.BLOCKED_WAITING_PROVIDER)

    def test_a_blocked_run_leaves_the_worktree_alone(self) -> None:
        self.dirty = ["x.py"]
        self.drive(max_tasks=1)
        self.assertEqual(self.removed, [])


class TestCommitGuards(ProjectCase):
    def test_a_branch_touching_guarded_paths_is_refused(self) -> None:
        with (
            mock.patch.object(project, "_git", self.fake_git),
            mock.patch.object(
                local, "changed_paths", lambda *a, **k: ["ops/policy.json"]
            ),
        ):
            with self.assertRaises(project.Stop) as raised:
                project.commit_task_changes(self.root, self.root, 15, "t", base="base0")
        self.assertEqual(raised.exception.status, project.BLOCKED_HUMAN)

    def test_a_branch_carrying_a_credential_file_is_refused(self) -> None:
        with (
            mock.patch.object(project, "_git", self.fake_git),
            mock.patch.object(local, "changed_paths", lambda *a, **k: [".env.remote"]),
        ):
            with self.assertRaises(project.Stop) as raised:
                project.commit_task_changes(self.root, self.root, 15, "t", base="base0")
        self.assertIn("never be committed", raised.exception.detail)

    def test_runtime_state_can_never_be_committed(self) -> None:
        self.assertTrue(project.forbidden_paths([".agentops/local/config.json"]))
        self.assertTrue(project.forbidden_paths(["infra/tls/server.key"]))
        self.assertFalse(project.forbidden_paths(["services/api/app.py"]))


class TestTheWholeBacklog(ProjectCase):
    def test_the_loop_exits_complete_when_nothing_is_outstanding(self) -> None:
        ctx_progress = state.Paths(self.root).progress
        progress = state.read_json(ctx_progress)
        from services.agentops import backlog as backlog_mod

        progress["completed_tasks"] = sorted(backlog_mod.load(self.root).task_ids())
        state.write_json(ctx_progress, progress)
        self.reconciles = set()
        result = self.drive()
        self.assertEqual(result["status"], project.COMPLETE)
        self.assertEqual(result["merged"], [])

    def test_one_task_is_in_flight_at_a_time(self) -> None:
        """The next task is not selected until the previous one is merged."""
        self.dispatched = [self.ready(15, "b15"), self.ready(16, "b16")]
        self.reconciles = {15, 16}
        order: list[str] = []
        original = project.ship

        def watched(*args: Any, **kwargs: Any) -> dict[str, Any]:
            order.append(f"ship:{kwargs['task_id']}")
            return original(*args, **kwargs)

        def watched_run_once(root: Path, paths: Any, **kwargs: Any) -> dict[str, Any]:
            result = self.dispatched.pop(0)
            order.append(f"select:{result['task_id']}")
            return result

        self.fake_run_once = watched_run_once  # type: ignore[method-assign]
        with mock.patch.object(project, "ship", watched):
            self.drive(max_tasks=2)
        self.assertEqual(order, ["select:15", "ship:15", "select:16", "ship:16"])

    def test_cloud_autonomy_and_the_writer_cap_are_untouched(self) -> None:
        self.dispatched = [self.ready(15)]
        self.reconciles = {15}
        self.drive(max_tasks=1)
        policy = state.load_policy(state.Paths(self.root))
        self.assertFalse(policy["autonomy"]["enabled"])
        self.assertEqual(int(policy["autonomy"]["max_parallel_writers"]), 1)
        self.assertFalse(policy["gates"]["real_use_gate"])


class TestResume(ProjectCase):
    def test_the_breadcrumb_names_the_task_branch_worktree_and_pull_request(
        self,
    ) -> None:
        self.dispatched = [self.ready(15)]
        self.reconciles = {15}
        self.drive(max_tasks=1)
        stored = project.status(self.root, self.paths)
        self.assertEqual(stored["task_id"], 15)
        self.assertEqual(stored["branch"], "block-x-t1-fixture")
        self.assertEqual(stored["pull_request"], 101)
        self.assertIn("completed_tasks", stored)

    def test_a_blocked_run_records_the_status_and_the_detail(self) -> None:
        self.dirty = ["x.py"]
        self.dispatched = [self.ready(15)]
        self.drive(max_tasks=1)
        stored = project.status(self.root, self.paths)
        self.assertEqual(stored["status"], project.BLOCKED_LOCAL_CHECKOUT)
        self.assertTrue(stored["detail"])

    def test_the_provider_cooldown_survives_into_the_resume_view(self) -> None:
        local.mark_lane_exhausted(self.paths, local.CLAUDE_LANE)
        stored = project.status(self.root, self.paths)
        self.assertIn(local.CLAUDE_LANE, stored["provider_cooldowns"])

    def test_resume_reports_the_project_alongside_the_workers(self) -> None:
        from services.agentops import cli

        self.dispatched = [self.ready(15)]
        self.reconciles = {15}
        self.drive(max_tasks=1)
        args = cli.build_parser().parse_args(["--root", str(self.root), "resume"])
        with mock.patch("builtins.print") as printed:
            self.assertEqual(args.func(args), 0)
        payload = json.loads(printed.call_args[0][0])
        self.assertIn("workers", payload)
        self.assertEqual(payload["project"]["task_id"], 15)


if __name__ == "__main__":
    unittest.main()
