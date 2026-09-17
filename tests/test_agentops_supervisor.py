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


def only_branch(wanted: str) -> Any:
    """Merged is asked per branch now, so a blanket True completes everything."""

    def answer(branch: str, **_: Any) -> bool:
        return branch == wanted

    return answer


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
                "pull_request_merged",
                side_effect=only_branch("block-04-t15-coach-judgments"),
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
            mock.patch.object(reconcile, "pull_request_merged", return_value=False),
            mock.patch.object(reconcile, "branch_is_merged", return_value=False),
        ):
            ctx = coordinator.load_context(REPO_ROOT)
            ctx.tasks = {"leases": {}}
            before = set(state.completed_tasks(ctx.progress))
            found = reconcile._reconcile_unleased(ctx, REPO_ROOT, repo="o/r")

        self.assertEqual(found, [])
        self.assertEqual(set(state.completed_tasks(ctx.progress)), before)

    def test_an_unanswerable_query_completes_nothing(self) -> None:
        """Fail closed. Inventing completion releases dependent work early."""
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=1, stdout="")
            self.assertIsNone(reconcile.pull_request_merged("b", repo="o/r"))

    def test_it_closes_a_lease_left_open_against_its_own_completion(self) -> None:
        """A lease released as blocked before the work in fact landed.

        Leaving it non-terminal holds the task against a merge that already
        happened, so the coordinator would never advance past it.
        """
        with (
            mock.patch.object(
                reconcile,
                "pull_request_merged",
                side_effect=only_branch("block-04-t15-coach-judgments"),
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

    def test_an_empty_branch_is_not_a_merge(self) -> None:
        """The defect this guards: on 2026-09-17 Task 15 was recorded complete
        while its implementation sat uncommitted in its own worktree.

        The coordinator pre-creates a task branch at main. Until the worker
        commits, that branch is an ancestor of main with no commits of its own
        -- the same shape a fast-forward-merged branch has -- so reading
        ancestry as proof of a merge completes work that was never written.
        Ancestry is left real here; only the pull request is mocked, because
        the branch genuinely is an ancestor and must still not count.
        """
        branch = "block-04-t15-coach-judgments"
        if not reconcile.branch_is_merged(REPO_ROOT, branch):
            self.skipTest(f"{branch} is not present as an ancestor of main here")

        with mock.patch.object(reconcile, "pull_request_merged", return_value=False):
            ctx = coordinator.load_context(REPO_ROOT)
            ctx.tasks = {"leases": {"15": a_lease(branch=branch)}}
            ctx.progress = {
                "completed_tasks": sorted(
                    set(state.completed_tasks(ctx.progress)) - {15}
                ),
                "gates": {"real_use_gate": False},
            }
            reconcile._reconcile_unleased(ctx, REPO_ROOT, repo="o/r")

        self.assertNotIn(15, state.completed_tasks(ctx.progress))


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


HEAD = "deadbeef"


def graphql(
    threads: list[dict[str, Any]],
    reviews: list[dict[str, Any]] | list[str],
    *,
    head: str = HEAD,
) -> str:
    nodes = [
        {
            "state": r,
            "submittedAt": "2026-09-14T00:00:00Z",
            "author": {"login": "reviewer"},
            "commit": {"oid": head},
        }
        if isinstance(r, str)
        else r
        for r in reviews
    ]
    return json.dumps(
        {
            "data": {
                "repository": {
                    "pullRequest": {
                        "headRefOid": head,
                        "reviewThreads": {"nodes": threads},
                        "reviews": {"nodes": nodes},
                    }
                }
            }
        }
    )


def a_review(
    state: str,
    *,
    author: str = "reviewer",
    at: str = "2026-09-14T00:00:00Z",
    commit: str = HEAD,
) -> dict[str, Any]:
    return {
        "state": state,
        "submittedAt": at,
        "author": {"login": author},
        "commit": {"oid": commit},
    }


def thread(*, resolved: bool = False, outdated: bool = False) -> dict[str, Any]:
    return {
        "isResolved": resolved,
        "isOutdated": outdated,
        "comments": {
            "nodes": [
                {
                    "path": "services/api/app.py",
                    "line": 10,
                    "body": "This leaks another player's judgment.",
                }
            ]
        },
    }


class TestReviewVerdict(unittest.TestCase):
    """The merge gate. It decides, deterministically, without a model."""

    def verdict_for(
        self, stdout: str, code: int = 0, *, wait: bool = False
    ) -> dict[str, Any]:
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=code, stdout=stdout)
            return review.verdict("o/r", 42, require_submitted_review=wait)

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
        self.assertIn("\"$REVIEW_RESULT\" != 'success'", text)


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
        self.assertIn("--state open", text)
        self.assertIn("no open pull request for $BRANCH", text)

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
        self.assertIn("A human clears it", page)
        # And says where, which is not the runtime ledger.
        self.assertIn("ops/policy.json", page)

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


class TestIndependentReviewFindings(unittest.TestCase):
    """The five findings independent review left on this change itself.

    Each was a way the loop stopped, spent a budget on nothing, or merged
    something unreviewed, so each keeps a test rather than a line in a commit
    message.
    """

    def verdict_for(self, stdout: str, *, wait: bool = False) -> dict[str, Any]:
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0, stdout=stdout)
            return review.verdict("o/r", 42, require_submitted_review=wait)

    # 1. A reviewer reached by mention answers asynchronously.

    def test_a_mention_reviewer_does_not_pass_before_it_answers(self) -> None:
        """The job that posts `@codex review` succeeds immediately.

        Reading the review state right then finds nothing, which is
        indistinguishable from a clean review -- and would merge a pull request
        nobody had looked at yet.
        """
        result = self.verdict_for(graphql([], []), wait=True)
        self.assertEqual(result["verdict"], "pending")
        self.assertGreaterEqual(result["blocking"], 1)

    def test_it_passes_once_that_review_lands_on_this_head(self) -> None:
        result = self.verdict_for(graphql([], [a_review("COMMENTED")]), wait=True)
        self.assertEqual(result["verdict"], "pass")

    def test_a_review_of_an_older_commit_does_not_count(self) -> None:
        """A repair moves the branch on; the old review judged other code."""
        stale = a_review("COMMENTED", commit="0ldc0de")
        self.assertEqual(
            self.verdict_for(graphql([], [stale]), wait=True)["verdict"], "pending"
        )

    def test_an_action_reviewer_passes_without_a_submitted_review(self) -> None:
        """It posts inline comments synchronously, so silence really is clean."""
        self.assertEqual(self.verdict_for(graphql([], []))["verdict"], "pass")

    def test_the_workflow_waits_only_for_the_mention_mechanism(self) -> None:
        text = read("agentops-review.yml")
        self.assertIn("github-mention", text)
        self.assertIn("--require-submitted-review", text)

    def test_an_arriving_review_recomputes_the_verdict(self) -> None:
        """Otherwise a pending verdict never becomes a pass and nothing merges."""
        text = read("agentops-review.yml")
        self.assertIn("pull_request_review:", text)
        self.assertIn("types: [submitted, dismissed]", text)

    def test_an_arriving_review_does_not_ask_for_another_one(self) -> None:
        text = read("agentops-review.yml")
        self.assertIn("github.event_name == 'pull_request' &&", text)

    # 2. Only each reviewer's latest review counts.

    def test_an_approval_supersedes_that_reviewers_earlier_objection(self) -> None:
        """Summing history keeps a repaired branch red forever, which spends
        the repair ceiling achieving nothing and blocks the task for good."""
        reviews = [
            a_review("CHANGES_REQUESTED", at="2026-09-14T00:00:00Z"),
            a_review("APPROVED", at="2026-09-14T01:00:00Z"),
        ]
        result = self.verdict_for(graphql([], reviews))
        self.assertEqual(result["changes_requested_reviews"], 0)
        self.assertEqual(result["verdict"], "pass")

    def test_another_reviewers_objection_still_counts(self) -> None:
        reviews = [
            a_review("APPROVED", author="one"),
            a_review("CHANGES_REQUESTED", author="two"),
        ]
        self.assertEqual(
            self.verdict_for(graphql([], reviews))["changes_requested_reviews"], 1
        )

    def test_a_comment_is_not_a_verdict(self) -> None:
        """GitHub records COMMENTED for every inline batch. Letting it override
        a standing objection would turn a rejection into an approval."""
        reviews = [
            a_review("CHANGES_REQUESTED", at="2026-09-14T00:00:00Z"),
            a_review("COMMENTED", at="2026-09-14T02:00:00Z"),
        ]
        self.assertEqual(
            self.verdict_for(graphql([], reviews))["changes_requested_reviews"], 1
        )

    def test_latest_state_ignores_advisory_records(self) -> None:
        states = review.latest_review_states(
            [a_review(s) for s in ("COMMENTED", "PENDING", "DISMISSED")]
        )
        self.assertEqual(states, {})

    # 3. A fork must not reach this credentialed workflow.

    def test_repair_requires_the_failure_to_come_from_this_repository(self) -> None:
        """A fork may name its branch after the live task and fail Quality on
        purpose. Repair lookup is by task number, so without this check that
        run spends the real task's budget and dispatches a credentialed worker
        at the real branch."""
        text = read("agentops-pr.yml")
        self.assertIn(
            "github.event.workflow_run.head_repository.full_name == github.repository",
            text,
        )

    def test_repair_also_checks_the_branch_against_the_lease(self) -> None:
        """The task number alone does not prove which branch this is."""
        text = read("agentops-pr.yml")
        self.assertIn(".leases[$t].branch", text)

    # 4. A reviewer that could not run is not a code problem.

    def test_a_reviewer_failure_reruns_the_reviewer(self) -> None:
        """Sending it to the writer spends a review cycle, produces no commit,
        emits no `synchronize`, and leaves the pull request stuck forever."""
        text = read("agentops-pr.yml")
        self.assertIn("action=rerun-review", text)
        self.assertIn("gh run rerun", text)

    def test_only_a_real_finding_spends_a_review_cycle(self) -> None:
        text = read("agentops-pr.yml")
        self.assertIn('"$blocking" -gt 0', text)
        self.assertIn('"$readable" = ', text)

    # 5. The repair ledger write races the other state writers.

    def test_the_repair_write_retries_and_reapplies(self) -> None:
        text = read("agentops-pr.yml")
        self.assertIn("for attempt in 1 2 3 4 5", text)
        # Re-runs the mutation against freshly pulled state on each attempt,
        # which is safer than letting the push merge for it.
        self.assertIn("cli state-pull", text)
        self.assertIn("cli state-push", text)

    def test_a_reapplied_repair_does_not_spend_a_second_cycle(self) -> None:
        """Incrementing is not idempotent, so a contended push would otherwise
        charge two cycles for one failure."""
        tasks = {"leases": {"15": a_lease()}}
        settings = policy()
        first = leases.begin_repair(tasks, settings, 15, reason="ci", once_key="run-7")
        again = leases.begin_repair(tasks, settings, 15, reason="ci", once_key="run-7")
        self.assertEqual(first["ci_repair_cycles"], 1)
        self.assertEqual(again["ci_repair_cycles"], 1)

    def test_a_different_failure_still_spends_one(self) -> None:
        tasks = {"leases": {"15": a_lease()}}
        settings = policy()
        leases.begin_repair(tasks, settings, 15, reason="ci", once_key="run-7")
        second = leases.begin_repair(tasks, settings, 15, reason="ci", once_key="run-8")
        self.assertEqual(second["ci_repair_cycles"], 2)

    def test_the_workflow_passes_the_triggering_run_as_the_key(self) -> None:
        text = read("agentops-pr.yml")
        self.assertIn("--once-key", text)
        self.assertIn("FAILED_RUN_ID", text)


class TestSecondRoundReviewFindings(unittest.TestCase):
    """The second round of independent review, on the fixes for the first.

    Mostly one theme: a branch name is not evidence. Prefixes, task numbers and
    head refs are all attacker- or human-controlled, and three separate places
    were treating them as proof that this system wrote the branch.
    """

    def verdict_for(self, stdout: str, **kwargs: Any) -> dict[str, Any]:
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0, stdout=stdout)
            return review.verdict("o/r", 42, **kwargs)

    # A branch prefix is not proof of authorship.

    def test_repair_requires_the_lease_to_name_exactly_this_branch(self) -> None:
        """A person may open `task-15-whatever` too, and repair is looked up by
        task number, so a prefix alone would move the canonical task's lease
        and point a credentialed worker at a branch it does not name."""
        text = read("agentops-pr.yml")
        self.assertIn('if [ "$leased" != "$BRANCH" ]', text)

    def test_the_merge_rearm_only_touches_leased_branches(self) -> None:
        """The verdict context deliberately succeeds on a non-autonomous pull
        request, so arming on prefix would merge someone's work for them."""
        text = read("agentops-watchdog.yml")
        self.assertIn("ops/state/tasks.json", text)
        self.assertIn("grep -qxF", text)

    def test_completion_requires_the_branch_to_live_in_this_repository(self) -> None:
        """A merged fork pull request can carry a canonical branch name. Taking
        that as completion marks the task done and releases everything waiting
        on code main never received."""
        merged = {
            "number": 1,
            "headRepositoryOwner": {"login": "someone"},
            "headRepository": {"name": "Shoulder"},
        }
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0, stdout=json.dumps([merged]))
            self.assertFalse(
                reconcile.pull_request_merged(
                    "block-04-t15", repo="Kush-nagar/Shoulder"
                )
            )
            merged["headRepositoryOwner"] = {"login": "Kush-nagar"}
            run.return_value = mock.Mock(returncode=0, stdout=json.dumps([merged]))
            self.assertTrue(
                reconcile.pull_request_merged(
                    "block-04-t15", repo="Kush-nagar/Shoulder"
                )
            )

    def test_a_deleted_fork_is_not_this_repository(self) -> None:
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(
                returncode=0, stdout=json.dumps([{"number": 1}])
            )
            self.assertFalse(reconcile.pull_request_merged("b", repo="o/r"))

    def test_completion_is_asked_per_branch_not_from_a_listing(self) -> None:
        """A bounded listing silently forgets older merges, and a task whose
        pull request fell outside the window looks outstanding and is
        dispatched again."""
        source = Path(reconcile.__file__).read_text(encoding="utf-8")
        self.assertNotIn("def merged_branches", source)
        self.assertIn("pull_request_merged(branch, repo=repo", source)

    # The gate must not evaluate a truncated picture.

    def test_more_threads_than_the_window_fails_closed(self) -> None:
        payload = json.loads(graphql([], []))
        payload["data"]["repository"]["pullRequest"]["reviewThreads"]["totalCount"] = (
            review.THREAD_WINDOW + 1
        )
        result = self.verdict_for(json.dumps(payload))
        self.assertEqual(result["verdict"], "unknown")
        self.assertFalse(result["ok"])

    def test_more_reviews_than_the_window_fails_closed(self) -> None:
        payload = json.loads(graphql([], []))
        payload["data"]["repository"]["pullRequest"]["reviews"]["totalCount"] = (
            review.REVIEW_WINDOW + 1
        )
        self.assertEqual(self.verdict_for(json.dumps(payload))["verdict"], "unknown")

    def test_a_normal_pull_request_is_inside_the_window(self) -> None:
        self.assertEqual(self.verdict_for(graphql([], []))["verdict"], "pass")

    # The awaited review must be the chosen reviewer's.

    def test_someone_elses_review_does_not_end_the_wait(self) -> None:
        """Another integration commenting first would otherwise let the branch
        merge without the independent reviewer ever answering."""
        other = a_review("COMMENTED", author="some-other-bot")
        result = self.verdict_for(
            graphql([], [other]),
            require_submitted_review=True,
            reviewer_login="chatgpt-codex-connector",
        )
        self.assertEqual(result["verdict"], "pending")

    def test_the_chosen_reviewers_review_does_end_it(self) -> None:
        mine = a_review("COMMENTED", author="chatgpt-codex-connector[bot]")
        result = self.verdict_for(
            graphql([], [mine]),
            require_submitted_review=True,
            reviewer_login="chatgpt-codex-connector",
        )
        self.assertEqual(result["verdict"], "pass")

    def test_the_reviewer_identity_is_configured_not_hardcoded(self) -> None:
        lane = policy()["lanes"]["codex_cloud"]
        self.assertTrue(lane.get("review_bot_login"))

    def test_the_reviewer_command_reports_what_the_gate_needs(self) -> None:
        """The gate reads both out of `cli reviewer`. Without them it either
        cannot wait at all, or waits for anyone."""
        from services.agentops import cli

        assert cli.__file__ is not None
        text = Path(cli.__file__).read_text(encoding="utf-8")
        self.assertIn('"mechanism": reviewer.mechanism', text)
        self.assertIn('"review_bot_login"', text)

    # An intentional pending verdict is not a reviewer failure.

    def test_a_pending_verdict_is_left_to_answer(self) -> None:
        """`gh run rerun --failed` reruns dependencies, so rerunning a pending
        review reposts the mention and fails again until it answers."""
        text = read("agentops-pr.yml")
        self.assertIn("if [ \"$decision\" = 'pending' ]", text)

    def test_triage_asks_the_verdict_the_same_way_the_gate_does(self) -> None:
        text = read("agentops-pr.yml")
        self.assertIn("--require-submitted-review", text)
        self.assertIn("--reviewer-login", text)

    # Failures must be visible, not swallowed.

    def test_a_failed_reviewer_rerun_is_not_reported_as_success(self) -> None:
        """This completed run is the only reaction that will fire for that
        failed review; nothing else retries one."""
        text = read("agentops-pr.yml")
        rerun = text.split("- name: Run the reviewer again", 1)[1].split("- name:", 1)[
            0
        ]
        self.assertIn("set -euo pipefail", rerun)
        self.assertNotIn("|| echo", rerun)

    def test_a_repair_that_was_never_recorded_does_not_dispatch(self) -> None:
        """Otherwise the cycle is invisible to the ceiling and the next failure
        is charged as the first, so repairs run past the bound indefinitely."""
        text = read("agentops-pr.yml")
        self.assertIn("pushed=false", text)
        self.assertIn("if [ \"$pushed\" != 'true' ]", text)
        self.assertIn("refusing to dispatch", text)

    # Orchestrator code must not run from the branch under review.

    def test_the_brief_is_built_before_the_task_branch_is_checked_out(self) -> None:
        """It runs orchestrator code with a repository token, and on a repair
        the branch under repair is agent-written."""
        text = read("agentops-worker.yml")
        self.assertLess(
            text.index("- name: Build the task brief"),
            text.index("- name: Check out the task branch"),
        )

    def test_the_control_center_refresh_runs_from_trusted_code(self) -> None:
        """Checking out only the state files leaves services/agentops on the
        task branch, so a worker could edit it and run it with the token."""
        text = read("agentops-worker.yml")
        report = text.split("\n  finalize:", 1)[1]
        self.assertIn("ref: ${{ github.event.repository.default_branch }}", report)
        # `contents: write` is unavoidable here -- this job pushes the state
        # branch -- so what bounds it is that the code it runs comes from the
        # default branch and never from the task branch, plus the absence of
        # every other write scope.
        self.assertNotIn("actions: write", report)
        self.assertNotIn("pull-requests: write", report)
        self.assertNotIn("id-token: write", report)

    def test_no_step_in_the_work_job_refreshes_the_control_center(self) -> None:
        text = read("agentops-worker.yml")
        work = text.split("  work:", 1)[1].split("\n  finalize:", 1)[0]
        self.assertNotIn("cli control-center", work)

    # Answering a thread is what unblocks the branch.

    def test_a_review_repair_is_told_how_to_resolve_a_thread(self) -> None:
        """The gate counts unresolved threads and cannot tell "already fixed"
        from "ignored". A fix made away from the flagged line leaves its thread
        standing, and the branch then stays blocked through every remaining
        repair cycle -- the most likely way a task fails from there."""
        from services.agentops import brief

        text = brief.render(REPO_ROOT, 15, repair="review")
        self.assertIn("resolveReviewThread", text)
        self.assertIn("reviewThreads", text)

    def test_the_guidance_survives_a_failed_findings_fetch(self) -> None:
        """A review repair means threads exist by definition; if reading them
        failed, the writer needs this more, not less."""
        from services.agentops import brief

        missing = REPO_ROOT / "does-not-exist.json"
        text = brief.render(REPO_ROOT, 15, repair="review", findings=missing)
        self.assertIn("resolveReviewThread", text)

    def test_it_warns_against_resolving_what_was_not_addressed(self) -> None:
        """That hides a real defect from the one gate that would catch it."""
        from services.agentops import brief

        text = brief.render(REPO_ROOT, 15, repair="review")
        self.assertIn("Resolve only what you actually answered", text)

    def test_a_ci_repair_is_not_told_about_threads(self) -> None:
        from services.agentops import brief

        self.assertNotIn(
            "resolveReviewThread", brief.render(REPO_ROOT, 15, repair="ci")
        )


class TestShellOutputIsDecodedExplicitly(unittest.TestCase):
    """`text=True` decodes with the locale codec.

    On a Windows checkout that is cp1252, and the first non-ASCII character in
    a review body, an issue title, or a branch name raises instead of
    returning. The verdict fails closed, so the effect is a merge gate that can
    never pass. Found by running the verdict against its own pull request.
    """

    def test_every_gh_and_git_call_forces_utf8(self) -> None:
        import ast

        from services.agentops import delegate, notify, watchdog

        modules = (review, control_center, notify, reconcile, watchdog, delegate)
        checked = 0
        for module in modules:
            assert module.__file__ is not None
            source = Path(module.__file__).read_text(encoding="utf-8")
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                target = ast.unparse(node.func)
                if target not in ("subprocess.run", "run"):
                    continue
                keywords = {kw.arg for kw in node.keywords}
                with self.subTest(f"{module.__name__}:{node.lineno}"):
                    self.assertIn("encoding", keywords)
                    self.assertIn("errors", keywords)
                checked += 1
        # A pass because nothing matched would be worthless.
        self.assertGreaterEqual(checked, 8)


if __name__ == "__main__":
    unittest.main()
