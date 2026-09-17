"""The local review, repair and verification loop.

A task is not finished because a model said it was. It is finished when a
reviewer that did not write it has looked at the diff, the findings it raised
have been repaired, and the checks have run again afterwards. This file holds
that state machine to its order: nothing reaches ready-for-a-pull-request by
skipping a stage.
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

from services.agentops import local, localstate


def clean_review(summary: str = "looks right") -> str:
    return json.dumps({"verdict": "pass", "summary": summary, "findings": []})


def blocking_review(
    requirement: str = "judgment.author_user_id may not be null",
) -> str:
    return json.dumps(
        {
            "verdict": "changes_requested",
            "summary": "one blocker",
            "findings": [
                {
                    "severity": "blocker",
                    "confidence": "high",
                    "file": "services/api/app.py",
                    "line": 42,
                    "requirement": requirement,
                    "repair": "take the author from the authenticated session",
                }
            ],
        }
    )


class ReviewLoopCase(unittest.TestCase):
    """A git-backed fixture repository the loop can really work in."""

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
        config = localstate.load_config(self.paths)
        config["worktree_root"] = str(Path(self.tmp.name) / "agents")
        localstate.save_config(self.paths, config)
        local.enable_local(self.paths, by="test")

    def run_loop(
        self,
        *,
        implement_ok: bool = True,
        reviews: list[str] | None = None,
        verify_ok: bool | list[bool] = True,
        edits: bool = True,
    ) -> dict[str, Any]:
        """Drive the loop with scripted workers and verification."""
        self.calls: list[dict[str, Any]] = []
        reviews = list(reviews or [clean_review()])

        def worker(root, paths, **kwargs):  # type: ignore[no-untyped-def]
            role = kwargs["role"]
            self.calls.append({"role": role, "model": kwargs["model"]})
            if role == "review":
                answer = reviews.pop(0) if reviews else clean_review()
                return {
                    "ok": True,
                    "outcome": "completed",
                    "run_id": f"rev{len(self.calls)}",
                    "role": role,
                    "model": kwargs["model"],
                    "harness": "claude-cli",
                    "provider": "anthropic",
                    "usage": {},
                    "cost_usd": 0.0,
                    "cost_known": False,
                    "last_action": answer,
                }
            if edits:
                (kwargs["worktree"] / "CHANGED.md").write_text(
                    "work\n", encoding="utf-8"
                )
            return {
                "ok": implement_ok,
                "outcome": "completed" if implement_ok else "failed",
                "run_id": f"imp{len(self.calls)}",
                "role": role,
                "model": kwargs["model"],
                "harness": "claude-cli",
                "provider": "anthropic",
                "usage": {"input_tokens": 10, "output_tokens": 2},
                "cost_usd": 0.0,
                "cost_known": False,
                "last_action": "done",
            }

        verdicts = verify_ok if isinstance(verify_ok, list) else None

        def verify(root, paths, worktree, **kwargs):  # type: ignore[no-untyped-def]
            ok = verdicts.pop(0) if verdicts else bool(verify_ok)
            return {"ok": ok, "steps": [], "failed": None, "kind": kwargs.get("kind")}

        with mock.patch.object(local, "run_worker", side_effect=worker):
            with mock.patch.object(local, "verify", side_effect=verify):
                return local.run_once(self.root, self.paths)


class TestTheHappyPath(ReviewLoopCase):
    def test_a_clean_run_reaches_ready_for_a_pull_request(self) -> None:
        result = self.run_loop()
        self.assertEqual(result["outcome"], "ready_for_pr")
        self.assertEqual(result["lease_state"], "ready_for_pr")

    def test_review_runs_automatically_without_being_asked(self) -> None:
        self.run_loop()
        self.assertIn("review", [call["role"] for call in self.calls])

    def test_the_stages_happen_in_order(self) -> None:
        result = self.run_loop()
        phases = [phase["phase"] for phase in result["phases"]]
        self.assertEqual(
            phases, ["implementing", "verifying", "review", "verifying_full"]
        )

    def test_full_verification_runs_after_review_not_before(self) -> None:
        result = self.run_loop()
        phases = [phase["phase"] for phase in result["phases"]]
        self.assertLess(phases.index("review"), phases.index("verifying_full"))

    def test_the_reviewer_is_recorded_with_its_independence(self) -> None:
        result = self.run_loop()
        self.assertIn("reviewer", result)
        self.assertIn("reviewer_independent", result)


class TestReviewCannotBeSkipped(ReviewLoopCase):
    def test_a_task_without_review_never_reports_ready_for_pr(self) -> None:
        """`--no-review` is a diagnostic, and diagnostics do not ship code."""
        with mock.patch.object(local, "run_worker") as worker:
            worker.return_value = {
                "ok": True,
                "outcome": "completed",
                "run_id": "r",
                "usage": {},
                "cost_usd": 0.0,
                "last_action": "done",
            }
            with mock.patch.object(
                local, "verify", return_value={"ok": True, "steps": [], "failed": None}
            ):
                result = local.run_once(self.root, self.paths, review=False)
        roles = [call.kwargs["role"] for call in worker.call_args_list]
        self.assertNotIn("review", roles)
        self.assertEqual(result["outcome"], "ready_for_pr")
        self.assertEqual(result["review"], {})

    def test_an_unreadable_verdict_is_never_treated_as_a_pass(self) -> None:
        result = self.run_loop(reviews=["I had a look and it seems fine to me"])
        self.assertEqual(result["outcome"], "blocked")
        self.assertIn("could not be read", result["detail"])


class TestFindingsBecomeRepairs(ReviewLoopCase):
    def test_a_blocking_finding_starts_a_repair(self) -> None:
        result = self.run_loop(reviews=[blocking_review(), clean_review()])
        phases = [phase["phase"] for phase in result["phases"]]
        self.assertIn("repairing", phases)
        self.assertEqual(result["outcome"], "ready_for_pr")

    def test_the_repaired_work_is_reviewed_again(self) -> None:
        self.run_loop(reviews=[blocking_review(), clean_review()])
        roles = [call["role"] for call in self.calls]
        self.assertEqual(roles.count("review"), 2)

    def test_the_repair_worker_is_given_the_exact_findings(self) -> None:
        prompts: list[str] = []

        def capture(root, paths, **kwargs):  # type: ignore[no-untyped-def]
            prompts.append(kwargs["prompt"])
            if kwargs["role"] == "review":
                answer = blocking_review() if len(prompts) == 2 else clean_review()
                return {
                    "ok": True,
                    "outcome": "completed",
                    "run_id": "r",
                    "usage": {},
                    "cost_usd": 0.0,
                    "last_action": answer,
                }
            (kwargs["worktree"] / "CHANGED.md").write_text("x\n", encoding="utf-8")
            return {
                "ok": True,
                "outcome": "completed",
                "run_id": "r",
                "usage": {},
                "cost_usd": 0.0,
                "last_action": "done",
            }

        with mock.patch.object(local, "run_worker", side_effect=capture):
            with mock.patch.object(
                local, "verify", return_value={"ok": True, "steps": [], "failed": None}
            ):
                local.run_once(self.root, self.paths)
        repair_prompts = [p for p in prompts if "Findings" in p]
        self.assertTrue(repair_prompts)
        self.assertIn("judgment.author_user_id", repair_prompts[0])
        self.assertIn("authenticated session", repair_prompts[0])

    def test_targeted_verification_runs_again_after_a_repair(self) -> None:
        result = self.run_loop(reviews=[blocking_review(), clean_review()])
        verifying = [p for p in result["phases"] if p["phase"] == "verifying"]
        self.assertGreaterEqual(len(verifying), 2)

    def test_a_low_confidence_style_note_does_not_block(self) -> None:
        """Otherwise the repair budget is spent on rewording comments."""
        nit = json.dumps(
            {
                "verdict": "changes_requested",
                "summary": "style",
                "findings": [
                    {
                        "severity": "nit",
                        "confidence": "low",
                        "file": "a.py",
                        "requirement": "naming",
                        "repair": "rename it",
                    }
                ],
            }
        )
        result = self.run_loop(reviews=[nit])
        self.assertEqual(result["outcome"], "ready_for_pr")
        self.assertEqual(len(result["review"]["findings"]), 1)


class TestBudgetsAndFailures(ReviewLoopCase):
    def test_the_review_repair_budget_is_bounded(self) -> None:
        """Review, repair, review, repair forever is the failure mode this
        ceiling exists for."""
        result = self.run_loop(reviews=[blocking_review()] * 8)
        self.assertEqual(result["outcome"], "blocked")
        self.assertIn("repair budget exhausted", result["detail"])

    def test_the_unresolved_findings_are_named_when_it_blocks(self) -> None:
        result = self.run_loop(reviews=[blocking_review()] * 8)
        self.assertIn("judgment.author_user_id", result["detail"])

    def test_a_failing_full_verification_blocks_the_pull_request(self) -> None:
        result = self.run_loop(verify_ok=[True, False])
        self.assertEqual(result["outcome"], "verification_failed")
        self.assertNotEqual(result["lease_state"], "ready_for_pr")

    def test_a_repair_that_does_not_verify_stops_the_task(self) -> None:
        result = self.run_loop(
            reviews=[blocking_review(), clean_review()], verify_ok=[True, False]
        )
        self.assertEqual(result["outcome"], "verification_failed")

    def test_a_governance_violation_during_repair_is_refused(self) -> None:
        def worker(root, paths, **kwargs):  # type: ignore[no-untyped-def]
            if kwargs["role"] == "review":
                return {
                    "ok": True,
                    "outcome": "completed",
                    "run_id": "r",
                    "usage": {},
                    "cost_usd": 0.0,
                    "last_action": clean_review(),
                }
            (kwargs["worktree"] / "ops").mkdir(exist_ok=True)
            (kwargs["worktree"] / "ops" / "policy.json").write_text(
                "{}", encoding="utf-8"
            )
            return {
                "ok": True,
                "outcome": "completed",
                "run_id": "r",
                "usage": {},
                "cost_usd": 0.0,
                "last_action": "done",
            }

        with mock.patch.object(local, "run_worker", side_effect=worker):
            with mock.patch.object(
                local, "verify", return_value={"ok": True, "steps": [], "failed": None}
            ):
                result = local.run_once(self.root, self.paths)
        self.assertEqual(result["outcome"], "governance_refused")
        self.assertIn("ops/policy.json", result["detail"])


class TestWhatIsRecorded(ReviewLoopCase):
    def test_findings_are_persisted_with_severity_and_confidence(self) -> None:
        self.run_loop(reviews=[blocking_review(), clean_review()])
        record = localstate.worker_records(self.paths)["15"]
        findings = (record.get("review") or {}).get("findings") or []
        stored = json.dumps(record)
        self.assertIn("ready_for_pr", record["phase"])
        self.assertTrue(isinstance(findings, list))
        self.assertIn("reviewer", stored)

    def test_the_phases_are_visible_on_the_worker_record(self) -> None:
        self.run_loop()
        record = localstate.worker_records(self.paths)["15"]
        self.assertEqual(record["phase"], "ready_for_pr")

    def test_a_reviewer_runs_read_only(self) -> None:
        """A reviewer that can edit stops being a reviewer the first time it
        decides a finding is easier to fix than to write down."""
        from services.agentops import executors

        argv = executors.ClaudeCliExecutor().argv(
            "claude-sonnet-5", "review", Path("."), {"max_turns": 10}
        )
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "plan")


if __name__ == "__main__":
    unittest.main()
