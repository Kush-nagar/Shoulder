"""An autonomous branch may not change what this system is permitted to do.

Moving the real-use gate onto the protected default branch did not make it
human-only: both required contexts are automated, so a branch this system wrote
could have edited `ops/policy.json` to grant itself the gate, and the system
would have authored, checked and merged its own permission to begin the
machine-learning phases AGENTS.md rule 5 forbids.

The first version of this guard lived entirely in a shell loop inside the
workflow, had never once executed -- pull request #24 was not an autonomous
branch, so its `if:` skipped it every time -- and silently matched no workflow
path at all, because `lstrip("./")` ate the leading dot of `.github/`.
"""

from __future__ import annotations

import unittest

from agentops_fixtures import REPO_ROOT

from services.agentops import governance

WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"


class TestWhatIsGuarded(unittest.TestCase):
    def test_editing_policy_is_refused(self) -> None:
        """The file the real-use gate now lives in."""
        self.assertEqual(
            governance.violations(["services/api/app.py", "ops/policy.json"]),
            ["ops/policy.json"],
        )

    def test_adding_a_workflow_is_refused(self) -> None:
        """A directory is named, not each file, so a workflow nobody listed
        yet is covered -- which is exactly the one that would slip through."""
        self.assertEqual(
            governance.violations([".github/workflows/anything.yml"]),
            [".github/workflows"],
        )

    def test_editing_the_gate_itself_is_refused(self) -> None:
        self.assertEqual(
            governance.violations([".github/workflows/agentops-review.yml"]),
            [".github/workflows"],
        )

    def test_the_rule_files_are_refused(self) -> None:
        for path in ("AGENTS.md", "CLAUDE.md"):
            with self.subTest(path):
                self.assertEqual(governance.violations([path]), [path])

    def test_approvals_are_refused(self) -> None:
        self.assertEqual(
            governance.violations([".github/CODEOWNERS"]), [".github/CODEOWNERS"]
        )

    def test_a_leading_dot_is_not_eaten(self) -> None:
        """`lstrip("./")` strips any leading run of those two characters, so
        `.github/workflows/...` arrived as `github/workflows/...` and matched
        nothing. The guard would have waved through every change it exists to
        stop."""
        self.assertEqual(
            governance.violations(["./.github/workflows/x.yml"]), [".github/workflows"]
        )

    def test_a_windows_separator_still_matches(self) -> None:
        self.assertEqual(
            governance.violations(["ops\\policy.json"]), ["ops/policy.json"]
        )

    def test_ordinary_task_work_is_allowed(self) -> None:
        """The guard must not block the work the system exists to do."""
        self.assertEqual(
            governance.violations(
                [
                    "services/api/app.py",
                    "apps/web/app/page.tsx",
                    "migrations/versions/0008_x.py",
                    "tests/test_api_x.py",
                    "docs/projects/project-05.md",
                ]
            ),
            [],
        )

    def test_the_runtime_ledger_is_not_guarded(self) -> None:
        """It is written constantly and lives on its own branch."""
        self.assertEqual(governance.violations(["ops/state/tasks.json"]), [])

    def test_a_lookalike_filename_is_not_a_match(self) -> None:
        self.assertEqual(governance.violations(["ops/policy.json.bak"]), [])

    def test_the_same_name_elsewhere_is_not_a_match(self) -> None:
        self.assertEqual(governance.violations(["docs/ops/policy.json"]), [])

    def test_nothing_changed_is_no_violation(self) -> None:
        self.assertEqual(governance.violations([]), [])
        self.assertEqual(governance.violations(["", "  "]), [])

    def test_each_guard_is_reported_once(self) -> None:
        found = governance.violations(
            [".github/workflows/a.yml", ".github/workflows/b.yml", "ops/policy.json"]
        )
        self.assertEqual(found, ["ops/policy.json", ".github/workflows"])

    def test_the_refusal_names_what_was_touched(self) -> None:
        text = governance.refusal(["ops/policy.json"])
        self.assertIn("ops/policy.json", text)
        self.assertIn("granting itself", text)


class TestTheGuardIsActuallyWired(unittest.TestCase):
    """A guard nothing calls, in a job nothing requires, blocks nothing."""

    def test_the_verdict_context_runs_it(self) -> None:
        text = (WORKFLOW_DIR / "agentops-review.yml").read_text(encoding="utf-8")
        verdict = text.split("\n  verdict:", 1)[1]
        self.assertIn("cli governance-check", verdict)

    def test_it_runs_before_the_verdict_is_decided(self) -> None:
        text = (WORKFLOW_DIR / "agentops-review.yml").read_text(encoding="utf-8")
        self.assertLess(
            text.index("cli governance-check"),
            text.index("- name: Decide the verdict"),
        )

    def test_it_applies_only_to_autonomous_branches(self) -> None:
        """A person changing policy does so from their own branch."""
        text = (WORKFLOW_DIR / "agentops-review.yml").read_text(encoding="utf-8")
        step = text.split("- name: Refuse an autonomous change", 1)[1]
        step = step.split("- name: Decide the verdict", 1)[0]
        self.assertIn("steps.scope.outputs.autonomous == 'true'", step)

    def test_an_unreadable_change_list_refuses(self) -> None:
        """Guessing is the one thing worse than blocking."""
        from unittest import mock

        from services.agentops import cli

        args = mock.Mock(repo="o/r", pull_request=1)
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=1, stdout="", stderr="boom")
            self.assertEqual(cli.cmd_governance_check(args), 1)

    def test_a_guarded_change_exits_non_zero(self) -> None:
        from unittest import mock

        from services.agentops import cli

        args = mock.Mock(repo="o/r", pull_request=1)
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(
                returncode=0, stdout="ops/policy.json\nservices/api/app.py\n", stderr=""
            )
            self.assertEqual(cli.cmd_governance_check(args), 1)

    def test_an_ordinary_change_exits_zero(self) -> None:
        from unittest import mock

        from services.agentops import cli

        args = mock.Mock(repo="o/r", pull_request=1)
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(
                returncode=0, stdout="services/api/app.py\ntests/test_x.py\n", stderr=""
            )
            self.assertEqual(cli.cmd_governance_check(args), 0)

    def test_the_brief_tells_the_writer_the_same_rule(self) -> None:
        from services.agentops import brief

        text = brief.render(REPO_ROOT, 15)
        for path in ("ops/policy.json", ".github/workflows"):
            with self.subTest(path):
                self.assertIn(path, text)

    def test_every_guarded_path_exists_or_is_deliberate(self) -> None:
        """A guard on a path that never existed is a typo nobody notices."""
        optional = {"CODEOWNERS", ".github/CODEOWNERS"}
        for guard in governance.GUARDED:
            if guard in optional:
                continue
            with self.subTest(guard):
                self.assertTrue((REPO_ROOT / guard).exists(), guard)


if __name__ == "__main__":
    unittest.main()
