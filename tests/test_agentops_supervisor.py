"""The cloud supervisor: merge gate, repair loop, lease-free reconciliation.

These cover the pieces that turn a system which can dispatch work into one
that finishes it without a human. Each test names the failure it exists to
catch, because every one of them is a way the autonomous loop silently stops.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from agentops_fixtures import REPO_ROOT, policy

from services.agentops import (
    control_center,
    coordinator,
    leases,
    reconcile,
    review,
    state,
)

WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"


def read(name: str) -> str:
    return (WORKFLOW_DIR / name).read_text(encoding="utf-8")


def a_lease(**overrides: Any) -> dict[str, Any]:
    lease = {
        "task_id": 15,
        "owner": "run-1",
        "branch": "block-04-t15-coach-judgments",
        "state": "ci",
        "assignment": {
            "lane": "claude_subscription",
            "harness_model": "claude-sonnet-5",
            "effort": "high",
        },
        "acquired_at": state.now(),
        "expires_at": state.now(),
        "heartbeat_at": state.now(),
        "attempts": 1,
        "worker_run_id": "999",
        "worker_run_attempt": "1",
        "pull_request": 42,
    }
    lease.update(overrides)
    return lease


class TestLeaseFreeReconciliation(unittest.TestCase):
    """Task 14 merged and stayed outstanding because nothing held its lease.

    Reconciliation read leases only, so a task whose lease was swept, released,
    or never written completed invisibly. The coordinator then handed the
    finished task to another writer -- which is exactly what `cli plan` was
    about to do before this was fixed.
    """

    def test_a_merged_branch_completes_its_task_without_any_lease(self) -> None:
        with (
            mock.patch.object(
                reconcile,
                "merged_branches",
                return_value={"block-04-t15-coach-judgments"},
            ),
            mock.patch.object(reconcile, "branch_is_merged", return_value=False),
        ):
            ctx = coordinator.load_context(REPO_ROOT)
            ctx.tasks = {"leases": {}}
            ctx.progress = {
                "completed_tasks": sorted(
                    set(state.completed_tasks(ctx.progress)) - {15}
                ),
                "gates": {"real_use_gate": False},
            }
            found = reconcile._reconcile_unleased(ctx, REPO_ROOT, repo="o/r")

        self.assertEqual([entry["task_id"] for entry in found], [15])
        self.assertIn(15, state.completed_tasks(ctx.progress))

    def test_a_branch_nobody_merged_is_left_alone(self) -> None:
        with (
            mock.patch.object(reconcile, "merged_branches", return_value=set()),
            mock.patch.object(reconcile, "branch_is_merged", return_value=False),
        ):
            ctx = coordinator.load_context(REPO_ROOT)
            ctx.tasks = {"leases": {}}
            before = set(state.completed_tasks(ctx.progress))
            found = reconcile._reconcile_unleased(ctx, REPO_ROOT, repo="o/r")

        self.assertEqual(found, [])
        self.assertEqual(set(state.completed_tasks(ctx.progress)), before)

    def test_an_unanswerable_listing_completes_nothing(self) -> None:
        """Fail closed. Inventing completion releases dependent work early."""
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=1, stdout="")
            self.assertEqual(reconcile.merged_branches(repo="o/r"), set())

    def test_it_closes_a_lease_left_open_against_its_own_completion(self) -> None:
        """A lease released as blocked before the work in fact landed.

        Leaving it non-terminal holds the task against a merge that already
        happened, so the coordinator would never advance past it.
        """
        with (
            mock.patch.object(
                reconcile,
                "merged_branches",
                return_value={"block-04-t15-coach-judgments"},
            ),
            mock.patch.object(reconcile, "branch_is_merged", return_value=False),
        ):
            ctx = coordinator.load_context(REPO_ROOT)
            ctx.tasks = {"leases": {"15": a_lease(state="blocked")}}
            ctx.progress = {
                "completed_tasks": sorted(
                    set(state.completed_tasks(ctx.progress)) - {15}
                ),
                "gates": {"real_use_gate": False},
            }
            reconcile._reconcile_unleased(ctx, REPO_ROOT, repo="o/r")

        self.assertEqual(ctx.tasks["leases"]["15"]["state"], "merged")

    def test_reconcile_runs_the_lease_free_pass(self) -> None:
        source = Path(reconcile.__file__).read_text(encoding="utf-8")
        self.assertIn("completed += _reconcile_unleased(ctx, root, repo=repo)", source)


class TestRepairBudget(unittest.TestCase):
    """Ordinary engineering failures must be repaired, and must stop somewhere."""

    def test_a_repair_does_not_spend_an_implementation_attempt(self) -> None:
        """Otherwise three lint failures exhaust a task that was nearly done."""
        tasks = {"leases": {"15": a_lease()}}
        lease = leases.begin_repair(tasks, policy(), 15, reason="ci")
        self.assertEqual(lease["attempts"], 1)
        self.assertEqual(lease["ci_repair_cycles"], 1)
        self.assertEqual(lease["state"], "repairing")

    def test_the_two_ceilings_are_independent(self) -> None:
        """A branch that keeps failing CI must not eat its review allowance."""
        tasks = {"leases": {"15": a_lease()}}
        settings = policy()
        for _ in range(int(settings["escalation"]["max_ci_repair_cycles"])):
            leases.begin_repair(tasks, settings, 15, reason="ci")
        lease = leases.begin_repair(tasks, settings, 15, reason="review")
        self.assertEqual(lease["review_repair_cycles"], 1)

    def test_it_stops_at_the_ceiling_rather_than_looping(self) -> None:
        tasks = {"leases": {"15": a_lease()}}
        settings = policy()
        ceiling = int(settings["escalation"]["max_ci_repair_cycles"])
        for _ in range(ceiling):
            leases.begin_repair(tasks, settings, 15, reason="ci")
        with self.assertRaises(leases.RepairBudgetExhausted):
            leases.begin_repair(tasks, settings, 15, reason="ci")

    def test_it_releases_the_finished_run_so_the_repair_can_start(self) -> None:
        """The worker refuses a lease held by a different run.

        Leaving the dead run attached would refuse every repair worker, and the
        branch would sit failing with nobody allowed to touch it.
        """
        tasks = {"leases": {"15": a_lease()}}
        lease = leases.begin_repair(tasks, policy(), 15, reason="ci")
        self.assertNotIn("worker_run_id", lease)
        self.assertNotIn("worker_run_attempt", lease)

    def test_the_repair_gets_a_fresh_lease_window(self) -> None:
        """Or the watchdog reclaims the branch part way through the fix."""
        tasks = {"leases": {"15": a_lease(expires_at="2000-01-01T00:00:00+00:00")}}
        lease = leases.begin_repair(tasks, policy(), 15, reason="ci")
        self.assertFalse(leases.is_stale(lease, policy()))

    def test_a_merged_task_is_not_repaired(self) -> None:
        tasks = {"leases": {"15": a_lease(state="merged")}}
        with self.assertRaises(leases.LeaseConflict):
            leases.begin_repair(tasks, policy(), 15, reason="ci")

    def test_an_unknown_failure_kind_is_refused(self) -> None:
        tasks = {"leases": {"15": a_lease()}}
        with self.assertRaises(ValueError):
            leases.begin_repair(tasks, policy(), 15, reason="vibes")


def graphql(threads: list[dict[str, Any]], reviews: list[str]) -> str:
    return json.dumps(
        {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {"nodes": threads},
                        "reviews": {"nodes": [{"state": s} for s in reviews]},
                    }
                }
            }
        }
    )


def thread(*, resolved: bool = False, outdated: bool = False) -> dict[str, Any]:
    return {
        "isResolved": resolved,
        "isOutdated": outdated,
        "comments": {
            "nodes": [
                {
                    "path": "services/api/app.py",
                    "line": 10,
                    "originalCommit": {"oid": "abc"},
                    "body": "This leaks another player's judgment.",
                }
            ]
        },
    }


class TestReviewVerdict(unittest.TestCase):
    """The merge gate. It decides, deterministically, without a model."""

    def verdict_for(self, stdout: str, code: int = 0) -> dict[str, Any]:
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=code, stdout=stdout)
            return review.verdict("o/r", 42)

    def test_a_clean_review_passes(self) -> None:
        result = self.verdict_for(graphql([], ["APPROVED"]))
        self.assertEqual(result["verdict"], "pass")
        self.assertEqual(result["blocking"], 0)

    def test_an_unresolved_finding_blocks(self) -> None:
        result = self.verdict_for(graphql([thread()], []))
        self.assertEqual(result["verdict"], "changes_requested")
        self.assertEqual(result["unresolved_threads"], 1)

    def test_changes_requested_blocks_even_with_no_threads(self) -> None:
        result = self.verdict_for(graphql([], ["CHANGES_REQUESTED"]))
        self.assertEqual(result["verdict"], "changes_requested")

    def test_a_resolved_finding_does_not_block(self) -> None:
        result = self.verdict_for(graphql([thread(resolved=True)], []))
        self.assertEqual(result["verdict"], "pass")

    def test_an_outdated_finding_does_not_block(self) -> None:
        """A pushed repair makes every earlier thread outdated.

        Counting those would make the branch permanently red no matter what the
        repair fixed, so the loop could never reach merge. A reviewer that still
        objects re-posts against the new commit.
        """
        result = self.verdict_for(graphql([thread(outdated=True)], []))
        self.assertEqual(result["verdict"], "pass")

    def test_an_unreadable_review_state_fails_closed(self) -> None:
        """Merging on a question mark is the outcome worth avoiding."""
        result = self.verdict_for("", code=1)
        self.assertEqual(result["verdict"], "unknown")
        self.assertGreaterEqual(result["blocking"], 1)
        self.assertFalse(result["ok"])

    def test_findings_are_summarised_not_reproduced(self) -> None:
        """A whole review body in state would bloat every write that quotes it."""
        long = thread()
        long["comments"]["nodes"][0]["body"] = "x" * 5000
        result = self.verdict_for(graphql([long], []))
        self.assertLessEqual(len(result["findings"][0]["summary"]), 300)


class TestMergeIsNativeAndGated(unittest.TestCase):
    """Nothing in this repository merges a pull request by itself.

    GitHub's auto-merge does it once the required contexts pass. That is why no
    workflow polls for green, and why no job holds a runner open waiting for a
    check that outlasts it.
    """

    def test_the_worker_enables_auto_merge_rather_than_merging(self) -> None:
        worker = read("agentops-worker.yml")
        self.assertIn('gh pr merge "$BRANCH" --auto --squash', worker)
        self.assertNotIn("--admin", worker)

    def test_no_workflow_forces_a_merge_past_the_checks(self) -> None:
        for path in sorted(WORKFLOW_DIR.glob("agentops-*.yml")):
            text = path.read_text(encoding="utf-8")
            with self.subTest(path.name):
                self.assertNotIn("--admin", text)
                self.assertNotIn("merge_method", text)

    def test_the_watchdog_re_arms_auto_merge_on_a_stranded_branch(self) -> None:
        """A worker that died after opening its pull request stops the loop on
        a success, which no failure path would ever recover."""
        watchdog = read("agentops-watchdog.yml")
        self.assertIn("--auto --squash", watchdog)
        self.assertIn("autoMergeRequest == null", watchdog)

    def test_the_verdict_reports_on_every_pull_request(self) -> None:
        """A required context that never runs leaves a pull request pending
        forever, including a human's."""
        text = read("agentops-review.yml")
        verdict = text.split("  verdict:", 1)[1]
        self.assertIn("if: always()", verdict)
        self.assertIn("autonomous=false", verdict)

    def test_an_incomplete_review_is_not_an_approval(self) -> None:
        text = read("agentops-review.yml")
        self.assertIn("REVIEW_RESULT: ${{ needs.review.result }}", text)
        self.assertIn("if [ \"$REVIEW_RESULT\" != 'success' ]", text)


class TestRepairWorkflow(unittest.TestCase):
    def test_it_only_reacts_to_a_real_failure_on_an_autonomous_branch(self) -> None:
        text = read("agentops-pr.yml")
        self.assertIn("conclusion == 'failure'", text)
        self.assertIn("head_branch, 'block-')", text)
        self.assertIn("head_branch, 'task-')", text)

    def test_it_runs_from_trusted_code_not_the_branch_under_review(self) -> None:
        """This job is credentialed and the branch is agent-written."""
        text = read("agentops-pr.yml")
        self.assertIn("workflow_run:", text)
        self.assertNotIn("pull_request_target", text)
        self.assertNotIn("github.event.workflow_run.head_sha", text)

    def test_it_carries_no_provider_secret(self) -> None:
        """Repair dispatches a worker; the worker holds the credential."""
        text = read("agentops-pr.yml")
        self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", text)
        self.assertNotIn("OPENROUTER_API_KEY", text)

    def test_one_reaction_per_branch(self) -> None:
        """Quality and the verdict finish seconds apart; two repairs would put
        two writers on one branch."""
        text = read("agentops-pr.yml")
        self.assertIn(
            "group: agentops-pr-${{ github.event.workflow_run.head_branch }}", text
        )
        self.assertIn("cancel-in-progress: false", text)

    def test_it_does_not_repair_a_closed_pull_request(self) -> None:
        text = read("agentops-pr.yml")
        self.assertIn("!= 'OPEN'", text)

    def test_it_respects_the_kill_switch(self) -> None:
        text = read("agentops-pr.yml")
        self.assertIn("AUTONOMY_ENABLED", text)

    def test_a_repair_reuses_the_writer_rather_than_burning_fallback(self) -> None:
        """A failing test is a code problem, not a provider problem."""
        text = read("agentops-pr.yml")
        self.assertIn("${{ steps.repair.outputs.lane }}", text)
        self.assertNotIn("cli plan", text)

    def test_the_repair_brief_replaces_the_task_brief(self) -> None:
        worker = read("agentops-worker.yml")
        self.assertIn('--repair "${REPAIR_REASON:-ci}"', worker)

    def test_repair_artefacts_never_land_on_the_branch(self) -> None:
        worker = read("agentops-worker.yml")
        self.assertIn("rm -f brief.md findings.json", worker)


class TestControlCenter(unittest.TestCase):
    def test_it_says_what_the_system_is_doing(self) -> None:
        with mock.patch.object(control_center, "pull_request_checks", return_value=[]):
            page = control_center.render(REPO_ROOT, repo=None)
        for heading in (
            "AUTONOMY STATUS",
            "Current task",
            "Agent roles",
            "Providers",
            "Backlog",
            "Blocked tasks",
            "Hard gates",
        ):
            self.assertIn(heading, page)

    def test_it_names_the_real_gate_and_what_clears_it(self) -> None:
        with mock.patch.object(control_center, "pull_request_checks", return_value=[]):
            page = control_center.render(REPO_ROOT, repo=None)
        self.assertIn("real_use_gate", page)
        self.assertIn("a human sets", page)

    def test_the_kill_switch_reads_as_paused_not_broken(self) -> None:
        with mock.patch.object(control_center, "pull_request_checks", return_value=[]):
            page = control_center.render(REPO_ROOT, repo=None)
        expected = (
            "RUNNING"
            if state.autonomy_enabled(state.load_policy(state.Paths(REPO_ROOT)))
            else "PAUSED"
        )
        self.assertIn(f"AUTONOMY STATUS: {expected}", page)

    def test_it_redacts_anything_credential_shaped(self) -> None:
        """The page is public to anyone who can read the repository."""
        source = Path(control_center.__file__).read_text(encoding="utf-8")
        self.assertIn("notify.redact", source)

    def test_it_rewrites_one_page_instead_of_adding_comments(self) -> None:
        source = Path(control_center.__file__).read_text(encoding="utf-8")
        self.assertIn("issue", source)
        self.assertIn("edit", source)
        self.assertNotIn("issue comment", source)

    def test_every_lease_state_has_a_name_a_reader_understands(self) -> None:
        for lease_state in leases.ACTIVE_STATES + leases.TERMINAL_STATES:
            self.assertIn(lease_state, control_center.STAGE_NAMES)


class TestFrontendIsNotAStoppingCondition(unittest.TestCase):
    """The loop must not stall on a canonical task that contains UI.

    Owner decision of 2026-09-14. Functional interface work is Claude's; final
    visual polish is a separate later pass, which is why the brief says so
    explicitly rather than leaving the writer to guess the scope.
    """

    def test_claude_may_write_the_interface_a_task_requires(self) -> None:
        self.assertTrue(policy()["lanes"]["claude_subscription"]["may_write_frontend"])

    def test_the_openrouter_restriction_is_unchanged(self) -> None:
        self.assertFalse(policy()["lanes"]["openrouter"]["may_write_frontend"])

    def test_every_remaining_phase_c_task_has_a_writer(self) -> None:
        from services.agentops import classify, coordinator, routing

        ctx = coordinator.load_context(REPO_ROOT)
        inputs = ctx.routing_inputs()
        for task_id in ctx.backlog.task_ids():
            task = ctx.backlog.tasks[task_id]
            if "Phase C" not in task.phase:
                continue
            if task_id in state.completed_tasks(ctx.progress):
                continue
            with self.subTest(task_id):
                routing.select(inputs, classify.classify(task))

    def test_the_brief_bounds_interface_work_to_functional(self) -> None:
        from services.agentops import brief

        text = brief.render(REPO_ROOT, 18)
        self.assertIn("keyboard operation", text)
        self.assertIn("visual redesign", text)

    def test_a_backend_task_gets_no_interface_section(self) -> None:
        from services.agentops import brief

        self.assertNotIn(
            'What "done" means for the user interface', brief.render(REPO_ROOT, 15)
        )


class TestNoSecretReachesAnUntrustedContext(unittest.TestCase):
    """The invariants the earlier reviews established, re-checked on the new
    workflow so the autonomy upgrade cannot quietly undo them."""

    def test_the_new_workflow_declares_least_privilege(self) -> None:
        text = read("agentops-pr.yml")
        self.assertIn("permissions: {}", text)
        self.assertNotIn("permissions: write-all", text)

    def test_every_action_is_pinned_to_a_commit(self) -> None:
        uses = re.compile(r"uses:\s*([^\s@]+)@([^\s#]+)")
        for path in sorted(WORKFLOW_DIR.glob("agentops-*.yml")):
            for name, ref in uses.findall(path.read_text(encoding="utf-8")):
                with self.subTest(f"{path.name}:{name}"):
                    self.assertRegex(ref, r"^[0-9a-f]{40}$")

    def test_the_verdict_job_holds_no_provider_credential(self) -> None:
        text = read("agentops-review.yml")
        verdict = text.split("  verdict:", 1)[1]
        self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", verdict)
        self.assertNotIn("OPENROUTER_API_KEY", verdict)


if __name__ == "__main__":
    unittest.main()
