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
        self.drafts: set[int] = set()

    def __call__(self, args: list[str], *, repo: str | None = None) -> Any:
        self.calls.append(list(args))
        if args[:2] == ["repo", "view"]:
            return completed(stdout=json.dumps({"nameWithOwner": "owner/repo"}))
        if args[:2] == ["pr", "list"]:
            branch = args[args.index("--head") + 1]
            number = self.pulls.get(branch)
            found = (
                [{"number": number, "isDraft": number in self.drafts}] if number else []
            )
            return completed(stdout=json.dumps(found))
        if args[:2] == ["pr", "ready"]:
            self.drafts.discard(int(args[2]))
            return completed(stdout="ready")
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
        if not self.dispatched:
            return {"dispatched": False, "reason": "no eligible task"}
        return self.dispatched.pop(0)

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

    def test_the_loop_is_not_stopped_by_its_own_ledger(self) -> None:
        """`reconcile` writes these two files as a task completes.

        That is the moment the loop wants the next task, and it used to find
        its own bookkeeping in the checkout and stop as
        BLOCKED_LOCAL_CHECKOUT, so it could never finish two in a row.
        """
        project.record_ledger(self.paths, self.root)
        self.dirty = ["ops/state/progress.json", "ops/state/tasks.json"]
        result = self.drive(max_tasks=1)
        self.assertNotEqual(result["status"], project.BLOCKED_LOCAL_CHECKOUT)

    def test_a_ledger_nobody_recorded_writing_still_stops_the_loop(self) -> None:
        """Exempt by content, never by name.

        `progress.json` is read as the truth about which tasks are done, so an
        uncommitted edit adding a task to `completed_tasks` would make the loop
        skip it and merge its dependent. Nothing recorded writing these bytes,
        so they are not accounted for.
        """
        self.dirty = ["ops/state/progress.json"]
        result = self.drive(max_tasks=1)
        self.assertEqual(result["status"], project.BLOCKED_LOCAL_CHECKOUT)
        self.assertEqual(result["changes"], ["ops/state/progress.json"])

    def test_a_ledger_edited_after_the_loop_wrote_it_stops_the_loop(self) -> None:
        """The recorded digest is of the bytes, so a later edit is caught."""
        project.record_ledger(self.paths, self.root)
        ledger = self.root / "ops" / "state" / "progress.json"
        ledger.write_text(
            json.dumps({"completed_tasks": [15, 16], "gates": {}}), encoding="utf-8"
        )
        self.dirty = ["ops/state/progress.json"]
        result = self.drive(max_tasks=1)
        self.assertEqual(result["status"], project.BLOCKED_LOCAL_CHECKOUT)

    def test_the_ledger_exemption_does_not_cover_the_rest_of_ops_state(self) -> None:
        """Only the two files the orchestrator maintains are accounted for."""
        project.record_ledger(self.paths, self.root)
        self.dirty = ["ops/state/progress.json", "ops/policy.json"]
        result = self.drive(max_tasks=1)
        self.assertEqual(result["status"], project.BLOCKED_LOCAL_CHECKOUT)
        self.assertEqual(result["changes"], ["ops/policy.json"])

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


class TestTheGatesFailClosed(ProjectCase):
    def setUp(self) -> None:
        super().setUp()
        self.dispatched = [self.ready(15)]
        self.reconciles = {15}

    def test_a_pull_request_reporting_no_checks_is_never_called_clean(self) -> None:
        """Checks that have not registered yet look exactly like none failing."""
        self.gh.ci = [json.dumps({"statusCheckRollup": [], "headRefOid": "d"})]
        result = self.drive(max_tasks=1)
        self.assertEqual(result["status"], project.BLOCKED_HUMAN)
        self.assertFalse(self.gh.merged)

    def test_checks_that_appear_late_are_waited_for_then_honoured(self) -> None:
        self.gh.ci = [
            json.dumps({"statusCheckRollup": [], "headRefOid": "d"}),
            rollup(("quality", "pass")),
        ]
        result = self.drive(max_tasks=1)
        self.assertTrue(result["merged"], result)

    def test_a_merged_pull_request_is_never_repaired(self) -> None:
        """A merged pull request keeps the check results it had.

        Task 18's merged and red, so the ship loop read it as failing and sent
        a writer to repair it once every couple of minutes -- against the
        Codex allowance the next task needed, on a branch whose work was
        already on main. Whether it is still open is asked before whether its
        checks pass.
        """
        # Merged by somebody other than this loop, which is how task 18's was:
        # the loop never called merge, so it never recorded one.
        self.gh.merged.append(101)
        self.gh.ci = [
            json.dumps(
                {
                    "statusCheckRollup": [
                        {"name": "quality", "bucket": "fail", "conclusion": "fail"}
                    ],
                    "headRefOid": "d",
                    "state": "MERGED",
                }
            )
        ]
        result = self.drive(max_tasks=1)
        self.assertTrue(result["merged"], result)
        self.assertEqual(
            [call for call in self.gh.calls if "repair" in " ".join(call)],
            [],
        )

    def test_an_open_pull_request_that_is_failing_is_still_repaired(self) -> None:
        """The guard is about merged, not about failing."""
        with mock.patch.object(project, "_gh", self.gh):
            self.gh.ci = [rollup(("quality", "fail"))]
            answer = project.ci_state(1, repo="owner/repo")
        self.assertEqual(answer["state"], "fail")
        self.assertFalse(answer["merged"])

    def test_an_empty_rollup_reads_as_pending_not_pass(self) -> None:
        with mock.patch.object(project, "_gh", self.gh):
            self.gh.ci = [json.dumps({"statusCheckRollup": [], "headRefOid": "d"})]
            self.assertEqual(project.ci_state(1, repo="owner/repo")["state"], "pending")

    def test_a_failed_fetch_stops_before_the_next_task_is_chosen(self) -> None:
        def refusing_git(root: Path, args: list[str]) -> Any:
            self.git_calls.append(list(args))
            if args[:1] == ["fetch"]:
                return completed(returncode=1, stdout="could not reach origin")
            if args[:1] == ["status"]:
                return completed(stdout="")
            if args[:1] == ["rev-parse"]:
                return completed(stdout="agentops/test")
            return completed()

        self.fake_git = refusing_git  # type: ignore[method-assign]
        result = self.drive(max_tasks=1)
        self.assertEqual(result["status"], project.BLOCKED_HUMAN)
        self.assertIn("fetch origin/main", result["detail"])
        self.assertEqual(self.removed, [])

    def test_a_reused_draft_pull_request_is_marked_ready_before_merging(self) -> None:
        self.gh.pulls["block-x-t1-fixture"] = 77
        self.gh.drafts.add(77)
        result = self.drive(max_tasks=1)
        self.assertTrue(self.gh.issued("pr", "ready"))
        self.assertEqual(self.gh.drafts, set())
        self.assertTrue(result["merged"], result)


class TestResumingAnInFlightTask(ProjectCase):
    """A run that died after `ready_for_pr` must pick that task back up.

    `run_once` correctly refuses to re-dispatch a task that is already waiting
    for its pull request, and the loop used to read that refusal as a human
    blocker -- so an interrupted run could never be resumed, which is the one
    thing resume exists for.
    """

    def setUp(self) -> None:
        super().setUp()
        self.reconciles = {15}
        self.ready(15)
        project.save(self.paths, pull_request=101)
        # What `run_once` writes when it starts a task. Resume reads this
        # rather than a note the coordinator kept, so that a coordinator
        # killed before it could write anything still leaves the branch
        # findable.
        localstate.save_worker(
            self.paths,
            "15",
            {
                "task_id": 15,
                "branch": "block-x-t1-fixture",
                "worktree": str(Path(self.tmp.name) / "agents" / "block-x-t1-fixture"),
            },
        )
        leases_file = localstate.read(self.paths.leases, {"leases": {}})
        leases_file["leases"] = {"15": {"task_id": 15, "state": "ready_for_pr"}}
        localstate.write(self.paths.leases, leases_file)

    def test_the_recorded_task_is_shipped_without_selecting_a_new_one(self) -> None:
        self.dispatched = []  # run_once must not be reached at all
        result = self.drive(max_tasks=1)
        self.assertEqual(len(result["merged"]), 1)
        self.assertEqual(result["merged"][0]["task_id"], 15)

    def test_the_recorded_branch_and_pull_request_are_reused(self) -> None:
        self.dispatched = []
        self.gh.pulls["block-x-t1-fixture"] = 101
        self.drive(max_tasks=1)
        self.assertEqual(self.gh.merged, [101])
        self.assertFalse(self.gh.issued("pr", "create"))

    def context(self) -> Any:
        from services.agentops import coordinator

        ctx = coordinator.load_context(self.root)
        ctx.tasks = local.load_leases(self.root, self.paths)
        return ctx

    def test_a_task_that_already_merged_is_not_resumed(self) -> None:
        progress = state.read_json(state.Paths(self.root).progress)
        progress["completed_tasks"] = sorted(
            set(state.completed_tasks(progress)) | {15}
        )
        state.write_json(state.Paths(self.root).progress, progress)
        self.assertIsNone(project.in_flight(self.context(), self.paths))

    def test_a_task_that_is_not_ready_for_its_pull_request_is_not_resumed(self) -> None:
        localstate.write(
            self.paths.leases, {"leases": {"15": {"task_id": 15, "state": "assigned"}}}
        )
        self.assertIsNone(project.in_flight(self.context(), self.paths))

    def test_a_vanished_worktree_is_not_resumed(self) -> None:
        """The worktree is the work. Without it there is nothing to ship."""
        localstate.save_worker(
            self.paths, "15", {"task_id": 15, "worktree": str(self.root / "gone")}
        )
        self.assertIsNone(project.in_flight(self.context(), self.paths))


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

    def test_an_env_example_is_documentation_rather_than_a_secret(self) -> None:
        """Four are tracked here, holding key names with empty values.

        Refusing them stopped task 22 after it had implemented, verified, been
        reviewed and passed the gated suite, for editing a file this
        repository deliberately keeps.
        """
        self.assertFalse(
            project.forbidden_paths(
                [
                    ".env.example",
                    "apps/web/.env.example",
                    "services/worker/.env.example",
                    "services/api/.env.sample",
                    "infra/.env.template",
                ]
            )
        )

    def test_a_real_env_file_is_still_refused(self) -> None:
        """The exception is the three documentation suffixes and nothing
        else: `.env.local` and `.env.remote` are what this exists to catch."""
        for path in (".env", ".env.local", ".env.remote", "apps/web/.env.production"):
            with self.subTest(path=path):
                self.assertTrue(project.forbidden_paths([path]))


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
        before = state.load_policy(state.Paths(self.root))
        self.dispatched = [self.ready(15)]
        self.reconciles = {15}
        self.drive(max_tasks=1)
        policy = state.load_policy(state.Paths(self.root))
        self.assertFalse(policy["autonomy"]["enabled"])
        # Unchanged, rather than equal to a number written out here: a run of
        # the loop must not edit governance, whatever the owner has set.
        self.assertEqual(policy["autonomy"], before["autonomy"])
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


class TestPostMergeFastForward(unittest.TestCase):
    """`main` must advance after a merge, ledger or no ledger.

    Exempting the ledger in the start-up guard alone was not enough, and
    independent review caught it: `fetch_main` asked the same checkout a
    different question, saw the ledger `reconcile` had just written, and
    silently declined to fast-forward. Worktrees are cut from `HEAD`, so the
    next task would have been branched from pre-merge code -- the exact
    failure `fetch_main`'s own comment says it exists to prevent.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "repo"
        (self.root / "ops" / "state").mkdir(parents=True)
        for name in ("progress.json", "tasks.json"):
            (self.root / "ops" / "state" / name).write_text("{}\n", encoding="utf-8")
        self.paths = localstate.ensure(localstate.LocalPaths(self.root))

    def run_fetch(
        self, dirty: list[str], branch: str = "main", *, recorded: bool = True
    ) -> list[list[str]]:
        calls: list[list[str]] = []
        if recorded:
            project.record_ledger(self.paths, self.root)

        def fake_git(root: Path, args: list[str]) -> Any:
            calls.append(list(args))
            if args[:1] == ["status"]:
                return completed(stdout="".join(f" M {p}\n" for p in dirty))
            if args[:1] == ["rev-parse"]:
                return completed(stdout=f"{branch}\n")
            return completed()

        with mock.patch.object(project, "_git", fake_git):
            project.fetch_main(self.root, self.paths)
        return calls

    def test_a_dirty_ledger_does_not_stop_the_fast_forward(self) -> None:
        calls = self.run_fetch(["ops/state/progress.json", "ops/state/tasks.json"])
        self.assertIn(["merge", "--ff-only", "origin/main"], calls)

    def test_a_ledger_nobody_recorded_writing_stops_the_fast_forward(self) -> None:
        """Both callers ask the same question, so both fail closed."""
        calls = self.run_fetch(["ops/state/progress.json"], recorded=False)
        self.assertNotIn(["merge", "--ff-only", "origin/main"], calls)

    def test_unaccounted_changes_still_stop_it(self) -> None:
        calls = self.run_fetch(["services/api/half-done.py"])
        self.assertNotIn(["merge", "--ff-only", "origin/main"], calls)

    def test_it_does_not_fast_forward_off_main(self) -> None:
        calls = self.run_fetch([], branch="block-04-t16-drafts")
        self.assertNotIn(["merge", "--ff-only", "origin/main"], calls)
