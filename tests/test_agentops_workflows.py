"""Workflow syntax, permissions, secret hygiene, and the watchdog."""

from __future__ import annotations

import copy
import json
import re
import unittest
from pathlib import Path
from typing import Any

from agentops_fixtures import REPO_ROOT, make_stale, policy

from services.agentops import brief, coordinator, leases, state, watchdog

WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
AGENTOPS_WORKFLOWS = sorted(WORKFLOW_DIR.glob("agentops-*.yml"))
# Actions must be pinned to a full commit SHA, as the existing CI workflow does.
USES = re.compile(r"^\s*-?\s*uses:\s*([^\s@]+)@([^\s#]+)", re.MULTILINE)
SHA = re.compile(r"^[0-9a-f]{40}$")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestWorkflowsExist(unittest.TestCase):
    def test_the_control_plane_workflows_are_present(self) -> None:
        names = {p.name for p in AGENTOPS_WORKFLOWS}
        self.assertEqual(
            names,
            {
                "agentops-coordinator.yml",
                "agentops-worker.yml",
                "agentops-watchdog.yml",
                "agentops-review.yml",
                "agentops-verify.yml",
                # Reacts to a failing check on an autonomous pull request.
                # Merging is not here on purpose: GitHub's auto-merge does that
                # once the required contexts pass, so nothing polls for green.
                "agentops-pr.yml",
            },
        )

    def test_workflows_have_the_structure_a_workflow_needs(self) -> None:
        """62. Structure, checked without a YAML parser.

        The locked environment ships no YAML library, and a test that skips
        itself is not a check. GitHub rejects malformed workflow YAML at push
        time, which is the real syntax gate; these assertions cover the
        structure that a parser alone would not catch anyway.
        """
        for path in AGENTOPS_WORKFLOWS:
            with self.subTest(path.name):
                text = read(path)
                self.assertRegex(text, r"(?m)^name: ")
                self.assertRegex(text, r"(?m)^on:")
                self.assertRegex(text, r"(?m)^jobs:")
                self.assertRegex(text, r"(?m)^  \w[\w-]*:\n(?:.*\n)*?    runs-on: ")
                self.assertNotIn("\t", text, "YAML must not contain tabs")

    def test_every_job_that_checks_out_can_read_contents(self) -> None:
        """A job inheriting `permissions: {}` cannot run actions/checkout."""
        for path in AGENTOPS_WORKFLOWS:
            text = read(path)
            for block in re.split(r"(?m)^  (?=\w[\w-]*:$)", text)[1:]:
                name = block.split(":", 1)[0]
                if "actions/checkout" not in block:
                    continue
                with self.subTest(f"{path.name}:{name}"):
                    self.assertRegex(
                        block,
                        r"contents: (read|write)",
                        f"job {name} checks out but grants itself no contents access",
                    )

    def test_existing_quality_workflow_is_untouched(self) -> None:
        """64. Bootstrap must not disturb the repository's own gate."""
        text = read(WORKFLOW_DIR / "ci.yml")
        self.assertIn("name: Quality", text)
        self.assertIn("./scripts/check.ps1", text)


class TestWorkflowPermissions(unittest.TestCase):
    """63. Least privilege, checked explicitly."""

    def test_every_workflow_denies_permissions_by_default(self) -> None:
        for path in AGENTOPS_WORKFLOWS:
            with self.subTest(path.name):
                self.assertIn(
                    "permissions: {}",
                    read(path),
                    "each workflow must start from no permissions",
                )

    def test_no_workflow_grants_blanket_write_all(self) -> None:
        for path in AGENTOPS_WORKFLOWS:
            with self.subTest(path.name):
                self.assertNotIn("permissions: write-all", read(path))

    def test_no_workflow_uses_pull_request_target(self) -> None:
        """Untrusted fork code must never run with write tokens or secrets."""
        for path in AGENTOPS_WORKFLOWS:
            with self.subTest(path.name):
                self.assertNotIn("pull_request_target", read(path))

    def test_the_coordinator_never_writes_product_code(self) -> None:
        """It opens the pull request Codex attaches to, and nothing more.

        The Codex lane is reached by mentioning @codex on a pull request, so
        one has to exist first. The coordinator creates that branch and pull
        request; it never runs a harness and never implements anything.
        """
        text = read(WORKFLOW_DIR / "agentops-coordinator.yml")
        self.assertIn("pull-requests: write", text)
        for harness in ("claude-code-action", "codex-action"):
            self.assertNotIn(harness, text)

    def test_watchdog_cannot_write_pull_requests(self) -> None:
        """Asserted per job, which is where a token is actually scoped.

        The sweep job pushes the default branch and dispatches workflows.
        Adding merge rights to that same token is the concentration this
        exists to prevent, so re-arming a stranded merge lives in its own job
        that can do nothing else. That is stricter than the single blanket
        grant this test used to check for.
        """
        text = read(WORKFLOW_DIR / "agentops-watchdog.yml")
        sweep = text.split("  sweep:", 1)[1].split("\n  rearm:", 1)[0]
        self.assertNotIn("pull-requests: write", sweep)

        rearm = text.split("  rearm:", 1)[1]
        self.assertIn("pull-requests: write", rearm)
        self.assertNotIn("contents: write", rearm)
        self.assertNotIn("actions: write", rearm)
        self.assertNotIn("issues: write", rearm)

    def test_verify_cannot_open_or_merge_pull_requests(self) -> None:
        """It proves lanes work; it must not be able to land anything."""
        text = read(WORKFLOW_DIR / "agentops-verify.yml")
        self.assertNotIn("pull-requests: write", text)
        # `actions: write` would let it dispatch other workflows. The guard job
        # mentions the permission only in prose, so check the declarations.
        for line in text.splitlines():
            self.assertNotEqual(line.strip(), "actions: write")

    def test_verify_refuses_a_dispatch_from_another_ref(self) -> None:
        """Pinning the checkout does not pin the workflow definition."""
        text = read(WORKFLOW_DIR / "agentops-verify.yml")
        self.assertIn("refusing a verification dispatch from", text)
        self.assertIn("needs: guard", text)

    def test_verify_never_enables_autonomy(self) -> None:
        text = read(WORKFLOW_DIR / "agentops-verify.yml")
        self.assertIn(".autonomy_enabled' plan.json)\" = 'false'", text)

    def test_worker_has_the_permissions_it_needs_and_no_more(self) -> None:
        text = read(WORKFLOW_DIR / "agentops-worker.yml")
        for needed in ("contents: write", "pull-requests: write", "id-token: write"):
            self.assertIn(needed, text)
        self.assertNotIn("actions: write", text)

    def test_every_action_is_pinned_to_a_commit_sha(self) -> None:
        for path in AGENTOPS_WORKFLOWS:
            for action, ref in USES.findall(read(path)):
                with self.subTest(f"{path.name}:{action}"):
                    self.assertRegex(ref, SHA, f"{action} is not pinned to a SHA")

    def test_concurrency_prevents_two_writers_on_one_branch(self) -> None:
        text = read(WORKFLOW_DIR / "agentops-worker.yml")
        self.assertIn("concurrency:", text)
        self.assertIn("group: agentops-worker-${{ inputs.branch }}", text)

    def test_state_writers_share_one_serialised_group(self) -> None:
        """Coordinator and watchdog both push ops/state to main.

        Separate groups let them interleave, which loses a lease recovery or
        fails the push outright.
        """
        for name in ("agentops-coordinator.yml", "agentops-watchdog.yml"):
            with self.subTest(name):
                text = read(WORKFLOW_DIR / name)
                self.assertIn("group: agentops-state", text)
                self.assertIn("cancel-in-progress: false", text)

    def test_the_coordinator_does_not_retrigger_itself(self) -> None:
        """It commits ops/state to main; without ignoring that path it loops."""
        text = read(WORKFLOW_DIR / "agentops-coordinator.yml")
        self.assertIn("- 'ops/state/**'", text)

    def test_state_pushes_rebase_before_pushing(self) -> None:
        for name in ("agentops-coordinator.yml", "agentops-watchdog.yml"):
            with self.subTest(name):
                self.assertIn("git pull --rebase", read(WORKFLOW_DIR / name))

    def test_the_worker_rechecks_its_assignment(self) -> None:
        """Dispatch inputs are caller-controlled, so policy is re-derived."""
        text = read(WORKFLOW_DIR / "agentops-worker.yml")
        self.assertIn("verify-assignment", text)

    def test_provider_health_is_probed_before_planning(self) -> None:
        """Lanes are seeded UNAVAILABLE; something has to lift them."""
        text = read(WORKFLOW_DIR / "agentops-coordinator.yml")
        self.assertIn("health --probe", text)


def shell_interpolations(text: str) -> list[tuple[int, str]]:
    """Lines inside a `run:` block that contain a ${{ }} expression."""
    found: list[tuple[int, str]] = []
    inside = False
    indent = 0
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if re.match(r"^-?\s*run:\s*\|?", stripped) and "run:" in stripped:
            inside = True
            indent = len(line) - len(line.lstrip())
            continue
        if not inside:
            continue
        if stripped and (len(line) - len(line.lstrip())) <= indent:
            inside = False
        elif "${{" in line:
            found.append((number, stripped))
    return found


class TestWorkflowSecretHygiene(unittest.TestCase):
    def test_no_expression_is_interpolated_into_a_shell(self) -> None:
        """44. Uncontrolled shell interpolation.

        GitHub substitutes ${{ }} textually before the shell sees it, so a
        crafted input could inject a command. Every value a run: block uses
        must arrive as an environment variable instead. Checking the rule
        rather than each case keeps it verifiable at a glance.
        """
        for path in AGENTOPS_WORKFLOWS:
            with self.subTest(path.name):
                self.assertEqual(
                    shell_interpolations(read(path)),
                    [],
                    "pass these through env: instead",
                )

    def test_dispatch_inputs_are_validated_before_use(self) -> None:
        text = read(WORKFLOW_DIR / "agentops-worker.yml")
        self.assertIn("Validate the dispatch inputs", text)
        for guarded in ("$TASK_ID", "$BRANCH", "$MODEL"):
            self.assertIn(guarded, text)

    def test_secrets_are_referenced_only_through_the_secrets_context(self) -> None:
        literal = re.compile(r"(sk-or-v1-|sk-proj-|ghp_|github_pat_)")
        for path in AGENTOPS_WORKFLOWS:
            with self.subTest(path.name):
                self.assertIsNone(literal.search(read(path)))

    def test_no_workflow_echoes_a_secret(self) -> None:
        bad = re.compile(r"echo[^\n]*secrets\.")
        for path in AGENTOPS_WORKFLOWS:
            with self.subTest(path.name):
                self.assertIsNone(bad.search(read(path)))

    def test_each_executable_lane_uses_its_declared_secret(self) -> None:
        """A secretless lane has no credential to reference; skip it rather
        than inventing one for it."""
        text = read(WORKFLOW_DIR / "agentops-worker.yml")
        for name in ("claude_subscription", "openrouter"):
            secret = policy()["lanes"][name]["secret"]
            self.assertIn(f"secrets.{secret}", text, secret)

    def test_no_workflow_needs_an_openai_api_key(self) -> None:
        """The Codex lane spends the ChatGPT subscription, not API billing."""
        for path in AGENTOPS_WORKFLOWS:
            with self.subTest(path.name):
                self.assertNotIn("OPENAI_API_KEY", read(path))

    def test_autonomy_is_guarded_before_any_work_starts(self) -> None:
        """51/61. The worker refuses to run while the kill switch is off."""
        text = read(WORKFLOW_DIR / "agentops-worker.yml")
        self.assertIn("AUTONOMY_ENABLED", text)
        self.assertIn("needs.guard.outputs.allowed == 'true'", text)

    def test_watchdog_only_restarts_work_when_autonomy_is_on(self) -> None:
        text = read(WORKFLOW_DIR / "agentops-watchdog.yml")
        self.assertIn("vars.AUTONOMY_ENABLED == 'true'", text)


class TestWatchdog(unittest.TestCase):
    """60. Recovery of stale leases and elapsed provider cooldowns."""

    def test_a_clean_repository_needs_no_recovery(self) -> None:
        result = watchdog.sweep(REPO_ROOT)
        self.assertEqual(result["recovered"], [])
        self.assertEqual(result["active_leases"], 0)

    def test_idle_is_false_while_autonomy_is_off(self) -> None:
        """The watchdog must not restart work the kill switch has stopped."""
        self.assertFalse(watchdog.sweep(REPO_ROOT)["idle"])

    def test_stale_lease_is_abandoned_and_its_checkpoint_kept(self) -> None:

        settings = policy()
        tasks: dict[str, Any] = {"leases": {}}
        leases.acquire(
            tasks,
            settings,
            task_id=14,
            owner="worker-a",
            branch="b",
            assignment={"lane": "claude_subscription"},
        )
        leases.checkpoint(
            tasks,
            14,
            "worker-a",
            state="implementing",
            commit="abc1234",
            remaining=["marking UI"],
        )
        make_stale(tasks["leases"]["14"], settings)

        self.assertTrue(leases.is_stale(tasks["leases"]["14"], settings))
        self.assertEqual(leases.active_leases(tasks, settings), [])
        # The checkpoint is what makes the next worker cheap; it must survive.
        self.assertEqual(tasks["leases"]["14"]["checkpoint"]["commit"], "abc1234")


class TestWorkerBrief(unittest.TestCase):
    """The brief is the worker's entire context; it must be complete and narrow."""

    def setUp(self) -> None:
        self.text = brief.render(REPO_ROOT, 14)

    def test_brief_names_the_task_and_branch(self) -> None:
        self.assertIn("Task 14", self.text)
        self.assertIn("Manual clip marking", self.text)
        self.assertIn("block-04-t14-manual-clip-marking", self.text)

    def test_brief_carries_the_overriding_rules(self) -> None:
        for rule in ("AGENTS.md", "row-level security", "Phase D gate"):
            self.assertIn(rule, self.text)

    def test_brief_states_the_verification_owed(self) -> None:
        self.assertIn("Playwright", self.text)
        self.assertIn("./scripts/check.ps1", self.text)

    def test_brief_limits_reading_to_the_named_documents(self) -> None:
        self.assertIn("docs/03-schema.md", self.text)
        self.assertIn("docs/05-ui.md", self.text)
        self.assertIn("Read nothing else", self.text)
        # A document this task does not name must not be pulled in.
        self.assertNotIn("docs/07-cv.md", self.text)

    def test_brief_protects_the_domain_vocabulary(self) -> None:
        self.assertIn("`observation`", self.text)

    def test_brief_includes_a_checkpoint_when_one_exists(self) -> None:
        ctx = coordinator.load_context(REPO_ROOT)
        original = copy.deepcopy(ctx.tasks)
        ctx.tasks.setdefault("leases", {})["14"] = {
            "task_id": 14,
            "state": "implementing",
            "checkpoint": {
                "state": "implementing",
                "commit": "deadbee",
                "complete": ["migration 0007"],
                "remaining": ["marking UI"],
                "next_action": "write the keyboard handler",
            },
        }
        state.write_json(ctx.paths.tasks, ctx.tasks)
        try:
            text = brief.render(REPO_ROOT, 14)
            self.assertIn("Checkpoint from a previous attempt", text)
            self.assertIn("deadbee", text)
            self.assertIn("write the keyboard handler", text)
        finally:
            state.write_json(ctx.paths.tasks, original)

    def test_unknown_task_is_refused(self) -> None:
        with self.assertRaises(SystemExit):
            brief.render(REPO_ROOT, 999)

    def test_brief_contains_no_secret_material(self) -> None:
        from services.agentops import notify

        self.assertEqual(notify.redact(self.text), self.text)


class TestDryRunEvidence(unittest.TestCase):
    """48. The dry run against the real backlog is the readiness proof."""

    def test_dry_run_selects_the_next_real_task_with_a_complete_plan(self) -> None:
        """Asserted as an invariant rather than against a task number.

        This used to pin Task 14, so finishing Task 14 failed the readiness
        proof -- the check had to be edited at every task boundary, which makes
        it a chore rather than a guard. What actually matters is that the plan
        is complete and internally consistent with the backlog it came from.
        """
        result = coordinator.dry_run(REPO_ROOT)
        ctx = coordinator.load_context(REPO_ROOT)
        task_id = result["task_id"]
        self.assertIsNotNone(task_id, result.get("blocked"))

        task = ctx.backlog.tasks[task_id]
        block = ctx.backlog.block_for_task(task_id)
        self.assertNotIn(task_id, state.completed_tasks(ctx.progress))
        self.assertEqual(result["block"], block.slug if block else None)
        self.assertEqual(result["prerequisites"], list(task.prerequisites))
        self.assertEqual(result["branch"], coordinator.branch_name(task, block))
        self.assertTrue(result["verification"])
        self.assertIsNone(result["blocked_reason"])
        self.assertIsNotNone(result["writer"])
        self.assertIsNotNone(result["reviewer"])

    def test_dry_run_is_serialisable_for_a_workflow_summary(self) -> None:
        json.dumps(coordinator.dry_run(REPO_ROOT), default=str)


if __name__ == "__main__":
    unittest.main()


class TestWorkerChangeDetection(unittest.TestCase):
    """A harness that commits its own work must not read as 'no change'."""

    def test_both_committed_and_uncommitted_work_count(self) -> None:
        text = read(WORKFLOW_DIR / "agentops-worker.yml")
        self.assertIn("origin/main...HEAD", text)
        self.assertIn("git diff --quiet HEAD --", text)

    def test_state_files_are_excluded_from_the_change_check(self) -> None:
        """A ledger write is not the worker having done the task."""
        text = read(WORKFLOW_DIR / "agentops-worker.yml")
        self.assertIn("':!ops/state'", text)


class TestSpendRecording(unittest.TestCase):
    """Budgets only bind if something actually records what was spent."""

    def test_the_worker_records_harness_reported_cost(self) -> None:
        text = read(WORKFLOW_DIR / "agentops-worker.yml")
        self.assertIn("cli spend", text)
        self.assertIn("total_cost_usd", text)
        self.assertIn('--task "$TASK_ID"', text)

    def test_the_worker_only_runs_lanes_it_can_execute(self) -> None:
        """Codex Cloud is delegated by mention, never dispatched here."""
        text = read(WORKFLOW_DIR / "agentops-worker.yml")
        self.assertIn("lane $LANE is not executable by this workflow", text)
        self.assertNotIn("codex-action", text)


class TestReviewWorkflow(unittest.TestCase):
    """34. The writer is never the only judge of its own work."""

    def setUp(self) -> None:
        self.text = read(WORKFLOW_DIR / "agentops-review.yml")

    def test_the_reviewer_is_actually_run(self) -> None:
        """The assignment used to be logged and never executed."""
        self.assertIn("cli reviewer --task", self.text)
        for lane in ("claude_subscription", "openrouter", "codex_cloud"):
            self.assertIn(f"needs.choose.outputs.lane == '{lane}'", self.text)

    def test_orchestrator_code_runs_from_the_base_revision(self) -> None:
        """A writer's branch must not run its own orchestrator with secrets.

        Choosing the reviewer executes repository code, so it runs from the
        base commit in a job that holds no credentials at all.
        """
        self.assertIn("ref: ${{ github.event.pull_request.base.sha }}", self.text)
        choose = self.text.split("  choose:", 1)[1].split("  review:", 1)[0]
        self.assertNotIn("secrets.", choose)

    def test_the_credentialed_job_checks_out_only_the_trusted_base(self) -> None:
        # Bounded at the next job. This asserts what the *credentialed* job
        # does, and reading to end of file would fold the uncredentialed
        # verdict job into it -- which does legitimately read the head ref,
        # holds no secret, and is covered separately.
        review = self.text.split("  review:", 1)[1].split("\n  verdict:", 1)[0]
        checkout = "actions/checkout@11d5960a326750d5838078e36cf38b85af677262"
        self.assertEqual(review.count("actions/checkout@"), 1)
        self.assertEqual(review.count(checkout), 1)
        checkout_step = review.split("- name: Review with Claude", 1)[0]
        self.assertIn(checkout, checkout_step)
        self.assertIn("ref: ${{ github.event.pull_request.base.sha }}", checkout_step)
        self.assertIn("fetch-depth: 1", checkout_step)
        self.assertIn("persist-credentials: false", checkout_step)
        self.assertLess(review.index(checkout), review.index("secrets."))
        self.assertNotIn("github.event.pull_request.head", review)
        self.assertNotIn("github.head_ref", review)

    def test_review_only_touches_branches_this_system_made(self) -> None:
        self.assertIn("startsWith(github.head_ref, 'block-')", self.text)

    def test_the_reviewer_cannot_write_repository_contents(self) -> None:
        self.assertIn("contents: read", self.text)
        self.assertNotIn("contents: write", self.text)

    def test_the_codex_reviewer_uses_the_documented_mention(self) -> None:
        """`@codex review` is the supported trigger, and it needs no key."""
        self.assertIn("@codex review", self.text)
        self.assertNotIn("openai-api-key", self.text)


class TestLoopCompletion(unittest.TestCase):
    """Without reconciliation the system dispatches work but never finishes it."""

    def test_the_coordinator_reconciles_merged_work(self) -> None:
        text = read(WORKFLOW_DIR / "agentops-coordinator.yml")
        self.assertIn("services.agentops.reconcile", text)

    def test_reconcile_reads_merge_state_from_git(self) -> None:
        from services.agentops import reconcile

        # An unmerged, non-existent branch is not complete.
        self.assertFalse(reconcile.branch_is_merged(REPO_ROOT, "no-such-branch"))

    def test_a_merged_ancestor_counts_as_merged(self) -> None:
        from services.agentops import reconcile

        # HEAD's own history is by definition contained in HEAD.
        self.assertTrue(reconcile.branch_is_merged(REPO_ROOT, "HEAD", base="HEAD"))

    def test_the_worker_records_a_provider_failure(self) -> None:
        """Failover states are useless if nothing ever enters them."""
        text = read(WORKFLOW_DIR / "agentops-worker.yml")
        self.assertIn("Record a provider failure", text)
        self.assertIn("--status DEGRADED", text)

    def test_the_worker_job_receives_the_kill_switch(self) -> None:
        """Scoped to the guard job alone, every worker would refuse."""
        text = read(WORKFLOW_DIR / "agentops-worker.yml")
        work = text.split("  work:", 1)[1]
        self.assertIn("AUTONOMY_ENABLED: ${{ vars.AUTONOMY_ENABLED }}", work)

    def test_the_worker_refuses_reserved_branches(self) -> None:
        """The job force-pushes what it is given, so main must be rejected."""
        text = read(WORKFLOW_DIR / "agentops-worker.yml")
        self.assertIn("main|master|HEAD|refs/*|*/HEAD", text)


class TestStateIntegrity(unittest.TestCase):
    """A generated ledger nobody reads by hand must never land corrupted."""

    def test_every_state_file_parses(self) -> None:
        paths = state.Paths(REPO_ROOT)
        for path in (
            paths.policy,
            paths.progress,
            paths.models,
            paths.providers,
            paths.tasks,
            paths.budget,
        ):
            with self.subTest(path.name):
                json.loads(path.read_text(encoding="utf-8"))

    def test_no_state_file_holds_conflict_markers(self) -> None:
        """A rebase between two state writers left these once, unnoticed."""
        paths = state.Paths(REPO_ROOT)
        for path in (paths.models, paths.providers, paths.tasks, paths.budget):
            with self.subTest(path.name):
                for line in path.read_text(encoding="utf-8").splitlines():
                    self.assertFalse(line.startswith(("<<<<<<<", ">>>>>>>")))

    def test_every_workflow_that_commits_state_validates_first(self) -> None:
        for path in AGENTOPS_WORKFLOWS:
            text = read(path)
            if "git add ops/state" not in text:
                continue
            with self.subTest(path.name):
                # Once before staging, and once after the rebase -- the rebase
                # is what leaves the markers behind.
                self.assertGreaterEqual(text.count("cli validate"), 2, path.name)


class TestCodexReviewFindings(unittest.TestCase):
    """Regressions for what the Codex Cloud review of PR #16 found."""

    def test_verify_never_runs_branch_code(self) -> None:
        """It holds every provider secret, so it runs only trusted code.

        With a `pull_request` trigger and a head checkout, a branch could edit
        services/agentops and read the credentials out of the runner -- and an
        autonomous writer's branch is exactly that kind of branch.
        """
        text = read(WORKFLOW_DIR / "agentops-verify.yml")
        self.assertNotIn("pull_request", text)
        self.assertNotIn("github.head_ref", text)

    def test_the_worker_guard_re_derives_the_routing_decision(self) -> None:
        """Checking fragments of policy missed most of what routing decides."""
        from services.agentops import cli

        source = Path(cli.__file__).read_text(encoding="utf-8")
        verify = source.split("def cmd_verify_assignment", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("routing.select(", verify)

    def test_the_reviewer_comes_from_the_recorded_writer(self) -> None:
        """Recomputing the writer can make a lane review its own work."""
        from services.agentops import cli

        source = Path(cli.__file__).read_text(encoding="utf-8")
        reviewer = source.split("def cmd_reviewer", 1)[1].split("\ndef ", 1)[0]
        self.assertIn('lease.get("assignment")', reviewer)
        self.assertIn("exclude_family", reviewer)

    def test_a_failed_lane_leaves_the_pool(self) -> None:
        from services.agentops import routing

        self.assertNotIn("DEGRADED", routing.USABLE_HEALTH)

    def test_a_probe_does_not_launder_a_failed_lane_back(self) -> None:
        """A credential being present is not evidence the provider works."""
        from services.agentops import cli

        source = Path(cli.__file__).read_text(encoding="utf-8")
        health = source.split("def cmd_health", 1)[1].split("\ndef ", 1)[0]
        for preserved in ("COOLDOWN", "AUTH_FAILED", "DEGRADED", "BUDGET_EXHAUSTED"):
            self.assertIn(f'"{preserved}"', health, preserved)

    def test_the_worker_attaches_its_own_run_to_the_lease(self) -> None:
        text = read(WORKFLOW_DIR / "agentops-worker.yml")
        self.assertIn("cli attach", text)
        self.assertIn("GITHUB_RUN_ID", text)


class TestThirdReviewFindings(unittest.TestCase):
    """Regressions for the third Codex review round."""

    def test_verify_checks_out_the_default_branch_not_the_dispatched_ref(
        self,
    ) -> None:
        """`gh workflow run --ref` chooses which branch's file runs.

        An unqualified checkout follows that branch, so the credentials would
        reach code that was never reviewed or merged.
        """
        text = read(WORKFLOW_DIR / "agentops-verify.yml")
        self.assertIn("ref: ${{ github.event.repository.default_branch }}", text)

    def test_a_provider_failure_is_pushed_not_just_written(self) -> None:
        """The failing job runs no later step, so it must push for itself."""
        text = read(WORKFLOW_DIR / "agentops-worker.yml")
        failure = text.split("Record a provider failure", 1)[1]
        self.assertIn("git push origin", failure.split("- name:", 1)[0])

    def test_the_hand_off_state_is_committed(self) -> None:
        """Delegation attaches the Codex PR after the ledger commit runs."""
        text = read(WORKFLOW_DIR / "agentops-coordinator.yml")
        self.assertIn("Commit what the hand-off recorded", text)

    def test_an_open_delegated_pull_request_counts_as_live(self) -> None:
        from unittest import mock

        from services.agentops import watchdog

        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0, stdout='{"state":"OPEN"}')
            self.assertFalse(watchdog.owner_finished({"pull_request": 42}))
            run.return_value = mock.Mock(returncode=0, stdout='{"state":"MERGED"}')
            self.assertTrue(watchdog.owner_finished({"pull_request": 42}))

    def test_an_unreadable_pull_request_holds_the_lease(self) -> None:
        """Fail closed: an outage must not hand a live branch to a second writer."""
        from unittest import mock

        from services.agentops import watchdog

        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=1, stdout="")
            self.assertFalse(
                watchdog.owner_finished(
                    {"pull_request": 42, "heartbeat_at": state.now()},
                    policy=policy(),
                )
            )

    def test_the_usage_check_acts_on_what_it_finds(self) -> None:
        """Reporting an overrun and doing nothing leaves the lane eligible."""
        from services.agentops import cli

        source = Path(cli.__file__).read_text(encoding="utf-8")
        usage = source.split("def cmd_usage", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("BUDGET_EXHAUSTED", usage)
        self.assertIn("record_spend", usage)


class TestFifthReviewFindings(unittest.TestCase):
    """Regressions for the fifth review round."""

    def test_a_provider_is_blamed_only_when_its_harness_failed(self) -> None:
        """`failure()` alone fires after any earlier step.

        A registry outage during dependency install would otherwise take a
        healthy provider lane out of the pool.
        """
        text = read(WORKFLOW_DIR / "agentops-worker.yml")
        self.assertIn("steps.claude.outcome == 'failure'", text)
        self.assertIn("steps.openrouter.outcome == 'failure'", text)

    def test_spend_and_the_pull_request_reach_the_ledger(self) -> None:
        """Both were written on the task branch and never carried back."""
        text = read(WORKFLOW_DIR / "agentops-worker.yml")
        self.assertIn("Carry spend and the pull request back to the ledger", text)
        self.assertIn("--pull-request", text)

    def test_an_ineligible_task_is_refused(self) -> None:
        """Eligibility was computed and then only reported."""
        from services.agentops import cli

        source = Path(cli.__file__).read_text(encoding="utf-8")
        verify = source.split("def cmd_verify_assignment", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("candidate.eligible", verify)
        self.assertIn("task is not eligible", verify)

    def test_liveness_fails_closed(self) -> None:
        from services.agentops import watchdog

        source = Path(watchdog.__file__).read_text(encoding="utf-8")
        self.assertIn("Fails closed", source)
        self.assertGreater(watchdog.UNRESOLVED_GRACE_MULTIPLE, 1)


class TestSeventhReviewFindings(unittest.TestCase):
    """Regressions for the seventh review round."""

    def test_the_worker_branch_is_bound_to_the_lease(self) -> None:
        text = read(WORKFLOW_DIR / "agentops-worker.yml")
        self.assertIn('--branch "$BRANCH"', text)

    def test_ledger_retries_redo_the_mutation(self) -> None:
        """Rebasing replays a commit built from state someone else replaced.

        The losing side's content survives and theirs is dropped, so each
        attempt must re-read the remote state and re-apply the change.
        """
        text = read(WORKFLOW_DIR / "agentops-worker.yml")
        for block in text.split("- name:"):
            if 'git push origin "HEAD:$DEFAULT_BRANCH"' not in block:
                continue
            with self.subTest(block.splitlines()[0].strip()[:50]):
                self.assertIn(
                    'git checkout "origin/$DEFAULT_BRANCH" -- ops/state', block
                )
                self.assertNotIn("git pull --rebase", block)

    def test_repeated_spend_cannot_double_count(self) -> None:
        """A retry re-applies the charge, so it must be idempotent."""
        from services.agentops import state as state_mod

        budget: dict[str, Any] = {}
        for _ in range(4):
            state_mod.record_spend(
                budget, "openrouter", 0.25, task_id=14, once_key="run-1"
            )
        self.assertEqual(state_mod.task_spend(budget, 14), 0.25)

    def test_a_different_run_still_records(self) -> None:
        from services.agentops import state as state_mod

        budget: dict[str, Any] = {}
        state_mod.record_spend(budget, "openrouter", 0.25, task_id=14, once_key="run-1")
        state_mod.record_spend(budget, "openrouter", 0.25, task_id=14, once_key="run-2")
        self.assertEqual(state_mod.task_spend(budget, 14), 0.5)

    def test_subscription_usage_never_touches_the_dollar_ledger(self) -> None:
        """An allowance is not money; charging it would block a task on a
        per-task ceiling nobody actually spent."""
        from services.agentops import cli

        source = Path(cli.__file__).read_text(encoding="utf-8")
        spend = source.split("def cmd_spend", 1)[1].split(chr(10) + "def ", 1)[0]
        self.assertIn('lane.get("billing") != "api"', spend)


class TestEighthReviewFindings(unittest.TestCase):
    """Regressions for the eighth review round."""

    def test_no_ledger_block_pushes_from_an_unverified_branch(self) -> None:
        """`set -uo pipefail` has no -e, so a failed checkout kept going.

        The run would stay on the task branch and the push would send that
        branch's content to the default branch.
        """
        text = read(WORKFLOW_DIR / "agentops-worker.yml")
        for block in text.split("- name:"):
            if 'git push origin "HEAD:$DEFAULT_BRANCH"' not in block:
                continue
            with self.subTest(block.splitlines()[0].strip()[:50]):
                self.assertIn("refusing to push", block)
                self.assertIn("git rev-parse --abbrev-ref HEAD", block)

    def test_spend_is_keyed_by_attempt_not_only_by_run(self) -> None:
        """A re-run keeps GITHUB_RUN_ID and increments GITHUB_RUN_ATTEMPT.

        Keying on the run alone made every attempt after the first look like a
        duplicate, so a real new provider charge was silently dropped.
        """
        text = read(WORKFLOW_DIR / "agentops-worker.yml")
        self.assertIn("GITHUB_RUN_ATTEMPT", text)
        self.assertNotIn('--once-key "run-${GITHUB_RUN_ID}"', text)


class TestSquashMergeCompletion(unittest.TestCase):
    """A squash-merged task must still be recognised as done.

    Squash and rebase merges rewrite the commits, so the branch tip is not an
    ancestor of main even though the work landed. Ancestry alone would leave
    the task outstanding and the coordinator would re-dispatch it forever.
    """

    def test_a_merged_pull_request_counts(self) -> None:
        from unittest import mock

        from services.agentops import reconcile

        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0, stdout='[{"number": 7}]')
            self.assertTrue(reconcile.pull_request_merged("block-04-t14"))
            run.return_value = mock.Mock(returncode=0, stdout="[]")
            self.assertFalse(reconcile.pull_request_merged("block-04-t14"))

    def test_an_unanswerable_query_is_not_a_merge(self) -> None:
        from unittest import mock

        from services.agentops import reconcile

        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=1, stdout="")
            self.assertIsNone(reconcile.pull_request_merged("block-04-t14"))

    def test_reconcile_consults_both_signals(self) -> None:
        from services.agentops import reconcile

        source = Path(reconcile.__file__).read_text(encoding="utf-8")
        self.assertIn("branch_is_merged(root, str(branch))", source)
        self.assertIn("pull_request_merged(str(branch), repo=repo", source)

    def test_completion_records_which_signal_proved_it(self) -> None:
        from services.agentops import reconcile

        source = Path(reconcile.__file__).read_text(encoding="utf-8")
        self.assertIn("squash or rebase merged", source)
        self.assertIn("ancestor of main", source)

    def test_only_a_merge_into_main_completes_a_task(self) -> None:
        """A branch retargeted to staging and merged there has not landed.

        Counting it would mark the task complete and release dependent work
        that is still waiting on code main has never seen.
        """
        from unittest import mock

        from services.agentops import reconcile

        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0, stdout="[]")
            reconcile.pull_request_merged("block-04-t14", base="main")
            command = run.call_args[0][0]
        self.assertIn("--base", command)
        self.assertIn("main", command)


class TestPostMergeVerifyFindings(unittest.TestCase):
    """The two defects the post-merge smoke test surfaced on 2026-09-13."""

    def setUp(self) -> None:
        self.text = (REPO_ROOT / ".github/workflows/agentops-verify.yml").read_text(
            encoding="utf-8"
        )

    def test_only_a_deliberate_dispatch_writes_state(self) -> None:
        """A merge fires this workflow and the coordinator at the same moment.
        Both committed ops/state to the default branch, and this one died in a
        rebase conflict, losing the verdicts it had just paid for."""
        for step in (
            "Qualify models against the synthetic suite",
            "Commit the qualification verdicts",
        ):
            after = self.text.split(f"- name: {step}", 1)[1].split("- name:", 1)[0]
            self.assertIn(
                "if: github.event_name == 'workflow_dispatch'",
                after,
                f"{step} must not run on push",
            )

    def test_the_claude_smoke_does_not_run_on_push(self) -> None:
        """claude-code-action rejects the push event outright, and the failure
        was then recorded against a lane that was in fact healthy."""
        after = self.text.split("- name: Smoke test the Claude subscription lane", 1)[
            1
        ].split("- name: Record", 1)[0]
        self.assertIn("if: github.event_name == 'workflow_dispatch'", after)

    def test_verify_shares_the_state_writer_concurrency_group(self) -> None:
        """Its own group let it run beside the coordinator."""
        self.assertIn("group: agentops-state", self.text)
        head = self.text.split("jobs:", 1)[0]
        self.assertIn("cancel-in-progress: false", head)

    def test_generated_state_is_not_style_gated(self) -> None:
        """`ops/state` is written by Python in the cloud, and Biome disagrees
        with it about float formatting (`5.9e-05` against `5.9e-5`). While it
        was covered, any coordinator run that wrote a small float turned the
        quality gate red on main, failing every worker's pull request for a
        reason no worker could fix. `cli validate` is what guards these files.
        """
        import json

        config = json.loads((REPO_ROOT / "biome.json").read_text(encoding="utf-8"))
        self.assertIn("!ops/state", config["files"]["includes"])


class TestVerdictDurability(unittest.TestCase):
    """Two verify runs qualified models and lost the verdicts in a rebase."""

    def _root(self) -> Path:
        import shutil
        import tempfile

        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        for relative in ("ops", "docs", "services"):
            shutil.copytree(REPO_ROOT / relative, tmp / relative)
        return tmp

    def _merge(self, root: Path, source: Path) -> dict[str, Any]:
        import contextlib
        import io

        from services.agentops import cli

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["--root", str(root), "merge-verdicts", "--from", str(source)])
        parsed: dict[str, Any] = json.loads(out.getvalue())
        return parsed

    def test_verdicts_survive_another_writer_landing_first(self) -> None:
        """The saved catalogue re-dates every model, which is what made a
        rebase conflict. Only the verdict fields may be carried across."""
        root = self._root()
        models = root / "ops/state/models.json"
        saved = json.loads(models.read_text(encoding="utf-8"))
        target = "deepseek/deepseek-v4.1-flash"
        saved["models"][target]["qualification"] = "QUALIFIED"
        saved["models"][target]["qualification_probes"] = [
            {"probe": "instruction_hierarchy", "passed": True}
        ]
        for record in saved["models"].values():
            record["last_seen"] = "2030-01-01T00:00:00+00:00"
        source = root / "verdicts.json"
        source.write_text(json.dumps(saved), encoding="utf-8")

        base_last_seen = json.loads(models.read_text(encoding="utf-8"))["models"][
            target
        ]["last_seen"]

        result = self._merge(root, source)
        self.assertEqual(result["applied"], [target])

        after = json.loads(models.read_text(encoding="utf-8"))["models"][target]
        self.assertEqual(after["qualification"], "QUALIFIED")
        self.assertEqual(
            after["qualification_probes"][0]["probe"], "instruction_hierarchy"
        )
        # The base state's own view of the catalogue is untouched.
        self.assertEqual(after["last_seen"], base_last_seen)

    def test_re_applying_the_same_verdicts_changes_nothing(self) -> None:
        """The step retries, so this must be safe to run more than once."""
        root = self._root()
        models = root / "ops/state/models.json"
        saved = json.loads(models.read_text(encoding="utf-8"))
        saved["models"]["qwen/qwen3.7-flash"]["qualification"] = "QUARANTINED"
        source = root / "verdicts.json"
        source.write_text(json.dumps(saved), encoding="utf-8")

        self.assertEqual(self._merge(root, source)["applied"], ["qwen/qwen3.7-flash"])
        self.assertEqual(self._merge(root, source)["applied"], [])

    def test_the_commit_step_no_longer_rebases_generated_state(self) -> None:
        text = (REPO_ROOT / ".github/workflows/agentops-verify.yml").read_text(
            encoding="utf-8"
        )
        after = text.split("- name: Commit the qualification verdicts", 1)[1]
        self.assertNotIn("git pull --rebase", after)
        self.assertIn("merge-verdicts", after)

    def test_the_verdict_commit_authenticates_its_own_remote_work(self) -> None:
        """A run that had already paid for its verdicts failed on the first
        fetch with "Password authentication is not supported", so this step
        carries the job token itself rather than trusting what the checkout
        left behind."""
        text = (REPO_ROOT / ".github/workflows/agentops-verify.yml").read_text(
            encoding="utf-8"
        )
        step = text.split("- name: Commit the qualification verdicts", 1)[1].split(
            "- name: Report", 1
        )[0]
        self.assertIn("git_auth fetch origin", step)
        self.assertIn("git_auth push origin", step)
        # The encoded credential is not the token itself, so the runner does
        # not mask it automatically.
        self.assertIn("::add-mask::$auth", step)
        # And it never reaches the remote URL or the repository config.
        self.assertNotIn("git remote set-url", step)
