"""Backlog parsing, dependency resolution, and task classification."""

from __future__ import annotations

import unittest

from agentops_fixtures import REPO_ROOT, policy, real_backlog

from services.agentops import backlog, classify, coordinator, state


class TestBacklogParsing(unittest.TestCase):
    """1. Canonical task parsing."""

    backlog: backlog.Backlog

    @classmethod
    def setUpClass(cls) -> None:
        cls.backlog = real_backlog()

    def test_every_numbered_task_is_parsed(self) -> None:
        ids = self.backlog.task_ids()
        self.assertEqual(ids, list(range(1, 32)), "docs/06-tasks.md defines Tasks 1-31")

    def test_titles_and_phases_are_captured(self) -> None:
        task = self.backlog.tasks[14]
        self.assertEqual(task.title, "Manual clip marking")
        self.assertIn("Phase C", task.phase)
        self.assertIn("Playwright", task.test)
        self.assertTrue(task.done)

    def test_blocks_are_parsed_from_the_roadmap(self) -> None:
        self.assertEqual(self.backlog.block_ids(), list(range(1, 11)))
        self.assertEqual(self.backlog.blocks[4].tasks, (14, 15, 16))
        block = self.backlog.block_for_task(14)
        assert block is not None
        self.assertEqual(block.slug, "block-04")

    def test_read_list_keeps_document_paths(self) -> None:
        self.assertIn("docs/03-schema.md", self.backlog.tasks[15].read)


class TestPrerequisiteParsing(unittest.TestCase):
    """2. Dependency resolution, including the shapes the real file uses."""

    def test_plain_list(self) -> None:
        self.assertEqual(backlog.parse_prerequisites("10, 15, 16")[0], (10, 15, 16))

    def test_en_dash_range_expands(self) -> None:
        self.assertEqual(backlog.parse_prerequisites("17–21")[0], (17, 18, 19, 20, 21))

    def test_trailing_prose_is_ignored(self) -> None:
        value = "25, 26 (evaluation go/no-go permits proceeding)"
        self.assertEqual(backlog.parse_prerequisites(value)[0], (25, 26))

    def test_prose_digits_are_not_task_numbers(self) -> None:
        value = "Task 30 and at least 2,000 human judgments"
        self.assertEqual(backlog.parse_prerequisites(value)[0], (30,))

    def test_narrative_prerequisites_yield_none(self) -> None:
        value = (
            "no numbered tasks; completed documentation reconciliation; see "
            "`docs/decisions/0012-task-1-local-acceptance.md`."
        )
        ids, gate = backlog.parse_prerequisites(value)
        self.assertEqual(ids, ())
        self.assertFalse(gate)

    def test_gate_prerequisite_is_flagged(self) -> None:
        ids, gate = backlog.parse_prerequisites("gate passed")
        self.assertEqual(ids, ())
        self.assertTrue(gate)

    def test_real_file_has_no_self_dependency(self) -> None:
        for task in real_backlog().tasks.values():
            self.assertNotIn(
                task.id, task.prerequisites, f"Task {task.id} depends on itself"
            )


class TestClassification(unittest.TestCase):
    """6-9. Complexity, risk, and category classification."""

    backlog: backlog.Backlog

    @classmethod
    def setUpClass(cls) -> None:
        cls.backlog = real_backlog()

    def _classify(
        self, task_id: int, prior_failures: int = 0
    ) -> classify.Classification:
        return classify.classify(
            self.backlog.tasks[task_id], prior_failures=prior_failures
        )

    def test_trivial_task_stays_trivial(self) -> None:
        task = backlog.Task(
            id=99,
            title="Fix a README typo",
            phase="Phase C",
            prerequisites=(),
            gated=False,
            read=(),
            test="spelling check passes.",
            done="the typo is gone.",
            body="Correct one misspelled word in README.md.",
        )
        self.assertEqual(classify.classify(task).complexity, "TRIVIAL")

    def test_schema_work_is_never_routine(self) -> None:
        """A new protected table needs RLS in the same task, so it is not routine."""
        result = self._classify(14)
        self.assertTrue(result.migration_risk)
        self.assertIn(result.complexity, ("COMPLEX", "CRITICAL"))

    def test_security_surface_forces_critical(self) -> None:
        result = self._classify(17)
        self.assertTrue(result.security_risk)
        self.assertEqual(result.complexity, "CRITICAL")

    def test_small_but_dangerous_task_is_critical(self) -> None:
        """Risk is not averaged with scope: a tiny RLS change is still critical."""
        task = backlog.Task(
            id=98,
            title="Tighten one RLS policy",
            phase="Phase C",
            prerequisites=(),
            gated=False,
            read=(),
            test="isolation test passes.",
            done="done.",
            body="Change one line in the player select policy.",
        )
        result = classify.classify(task)
        self.assertTrue(result.security_risk)
        self.assertEqual(result.complexity, "CRITICAL")

    def test_repeated_failure_escalates_to_extreme(self) -> None:
        base = self._classify(14)
        escalated = self._classify(14, prior_failures=2)
        self.assertNotEqual(base.complexity, "EXTREME")
        self.assertEqual(escalated.complexity, "EXTREME")

    def test_signed_url_expiry_is_not_destructive(self) -> None:
        """Storage tasks mention expiry constantly; that is not data deletion."""
        self.assertFalse(self._classify(13).destructive_risk)

    def test_retention_task_is_destructive(self) -> None:
        self.assertTrue(self._classify(22).destructive_risk)

    def test_frontend_and_backend_categories(self) -> None:
        self.assertEqual(self._classify(18).category, "frontend")
        self.assertEqual(self._classify(15).category, "backend")

    def test_unsignalled_task_defaults_to_backend(self) -> None:
        """The frontend lane carries a hard restriction; never enter it by accident."""
        task = backlog.Task(
            id=97,
            title="Write a note",
            phase="Phase C",
            prerequisites=(),
            gated=False,
            read=(),
            test="",
            done="",
            body="Record a decision.",
        )
        self.assertEqual(classify.classify(task).category, "backend")

    def test_context7_expectation_follows_external_libraries(self) -> None:
        """56. Context7 fires for external API surface, not internal logic."""
        self.assertTrue(self._classify(11).context7_expected)
        internal = backlog.Task(
            id=96,
            title="Refactor an internal helper",
            phase="Phase C",
            prerequisites=(),
            gated=False,
            read=(),
            test="unit tests pass.",
            done="done.",
            body="Simplify a pure function with no external dependency.",
        )
        self.assertFalse(classify.classify(internal).context7_expected)


class TestEligibility(unittest.TestCase):
    """3-5. Eligible-task selection against the real repository."""

    def setUp(self) -> None:
        self.ctx = coordinator.load_context(REPO_ROOT)

    def test_next_eligible_task_is_the_real_one(self) -> None:
        """The lowest-numbered task whose prerequisites are genuinely met.

        Asserted as an invariant rather than against a fixed number: pinning
        one meant finishing that task failed this check, so it had to be edited
        at every boundary instead of guarding anything.
        """
        candidate = coordinator.next_eligible(self.ctx)
        assert candidate is not None and candidate.block is not None
        done = state.completed_tasks(self.ctx.progress)
        self.assertNotIn(candidate.task.id, done)
        self.assertTrue(set(candidate.task.prerequisites) <= done)
        earlier = [
            task_id
            for task_id in self.ctx.backlog.task_ids()
            if task_id < candidate.task.id and task_id not in done
        ]
        self.assertEqual(earlier, [], "a lower-numbered task was skipped")
        self.assertIn(
            candidate.task.id, self.ctx.backlog.blocks[candidate.block.id].tasks
        )

    def test_completed_tasks_are_excluded(self) -> None:
        for task_id in state.completed_tasks(self.ctx.progress):
            candidate = coordinator.evaluate(self.ctx, self.ctx.backlog.tasks[task_id])
            self.assertFalse(candidate.eligible)
            self.assertIn("already complete", candidate.reasons)

    def test_blocked_dependency_prevents_eligibility(self) -> None:
        """Task 17 waits on 15 and 16, which are not done."""
        candidate = coordinator.evaluate(self.ctx, self.ctx.backlog.tasks[17])
        self.assertFalse(candidate.eligible)
        self.assertEqual(candidate.missing_prerequisites, [15, 16])

    def test_real_use_gate_blocks_phase_d(self) -> None:
        candidate = coordinator.evaluate(self.ctx, self.ctx.backlog.tasks[23])
        self.assertFalse(candidate.eligible)
        self.assertTrue(any("gate" in r for r in candidate.reasons), candidate.reasons)

    def test_phase_d_and_later_are_not_autonomous(self) -> None:
        """61/AGENTS rule 5: no ML work starts without a human clearing the gate."""
        self.assertFalse(self.ctx.policy["autonomy"]["allow_phase_d_and_later"])
        for task_id in (23, 28, 31):
            candidate = coordinator.evaluate(self.ctx, self.ctx.backlog.tasks[task_id])
            self.assertFalse(candidate.eligible)

    def test_dependencies_of_the_selected_task_are_satisfied(self) -> None:
        candidate = coordinator.next_eligible(self.ctx)
        assert candidate is not None
        satisfied, missing = state.dependencies_satisfied(
            self.ctx.progress, candidate.task.prerequisites
        )
        self.assertTrue(satisfied)
        self.assertEqual(missing, [])

    def test_branch_name_is_derived_from_the_task(self) -> None:
        candidate = coordinator.next_eligible(self.ctx)
        assert candidate is not None and candidate.block is not None
        branch = coordinator.branch_name(candidate.task, candidate.block)
        self.assertTrue(
            branch.startswith(f"{candidate.block.slug}-t{candidate.task.id}-")
        )
        self.assertRegex(branch, r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
        # The review and repair workflows read the task number back out of
        # the branch name with a greedy sed expression. If extraction and
        # derivation ever disagree, a failing branch silently stops being
        # repairable and the loop stalls there with no error anywhere.
        import re

        # Greedy prefix, exactly as the workflows' sed behaves: the LAST
        # -<digits>- in the name is the task number, not the first, which
        # is the block.
        extract = re.compile(r".*[-]t?([0-9]+)-")
        for task_id in self.ctx.backlog.task_ids():
            task = self.ctx.backlog.tasks[task_id]
            name = coordinator.branch_name(
                task, self.ctx.backlog.block_for_task(task_id)
            )
            recovered = extract.match(name + "-")
            with self.subTest(name):
                assert recovered is not None
                self.assertEqual(recovered.group(1), str(task_id))

    def test_progress_ledger_matches_the_roadmap(self) -> None:
        """The seeded ledger must agree with the block table it claims to finish."""
        done = state.completed_tasks(self.ctx.progress)
        for block_id in self.ctx.progress.get("completed_blocks", []):
            block = self.ctx.backlog.blocks[int(block_id)]
            self.assertTrue(
                set(block.tasks) <= done,
                f"block {block.slug} is marked complete but its tasks are not",
            )


class TestPolicyDocument(unittest.TestCase):
    """The policy file is load-bearing; keep its shape honest."""

    def setUp(self) -> None:
        self.policy = policy()

    def test_autonomy_is_disabled_in_the_repository(self) -> None:
        """51/61. The committed default must never be 'running'."""
        self.assertFalse(self.policy["autonomy"]["enabled"])

    def test_every_class_maps_to_a_defined_capability_class(self) -> None:
        classes = set(self.policy["capability_classes"])
        for mapping in self.policy["classification_to_class"].values():
            for name in mapping.values():
                self.assertIn(name, classes)

    def test_privacy_contract_is_strict(self) -> None:
        self.assertTrue(self.policy["privacy"]["require_zero_data_retention"])
        self.assertTrue(self.policy["privacy"]["deny_data_collection"])

    def test_budgets_are_present_and_bounded(self) -> None:
        for key in ("openrouter_daily_usd", "openai_daily_usd", "per_task_usd"):
            self.assertGreater(float(self.policy["budget"][key]), 0)
            self.assertLess(float(self.policy["budget"][key]), 100)


if __name__ == "__main__":
    unittest.main()
