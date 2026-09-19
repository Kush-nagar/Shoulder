"""The provider switch has to mean something.

It recorded a choice and changed a status line, while routing kept walking
every policy lane in priority order. Selecting `openrouter` therefore still ran
Claude whenever Claude was installed, which is the opposite of what the command
and its documentation promised.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest import mock

from agentops_fixtures import REPO_ROOT, installed_harnesses

from services.agentops import approvals, classify, coordinator, local, localstate


class ProviderCase(unittest.TestCase):
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
        self.ctx = coordinator.load_context(self.root)
        self.ctx.tasks = local.load_leases(self.root, self.paths)
        candidate = coordinator.next_eligible(self.ctx)
        assert candidate is not None, "the fixture backlog has no eligible task"
        self.candidate = candidate
        self.store = approvals.load(self.paths)

    @contextlib.contextmanager
    def openrouter_usable(self, *, installed: bool = True) -> Iterator[None]:
        """OpenCode installed and a key present -- both are required.

        The harness needs the credential as well as the binary, so a test that
        expects the OpenRouter lane to be selectable has to supply both.
        """
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-test-value"}):
            with installed_harnesses(claude=True, opencode=installed):
                yield

    def plan(self, provider: str, **kwargs: Any) -> Any:
        config = localstate.load_config(self.paths)
        config["provider"] = provider
        return local.local_plan(
            self.ctx, self.candidate, self.store, config=config, **kwargs
        )

    def approve_openrouter(self) -> str:
        """Approve an OpenRouter model the router would actually accept here.

        The candidate task is CRITICAL, so it earns a frontier class: a cheap
        model that cannot meet the class is not evidence about lane selection.
        """
        from services.agentops import routing

        inputs = self.ctx.routing_inputs()
        class_name = routing.capability_class(
            inputs.policy, classify.classify(self.candidate.task)
        )
        eligible = routing.eligible_models(inputs, class_name, "openrouter")
        self.assertTrue(eligible, f"no OpenRouter model meets {class_name}")
        chosen = eligible[0].id
        approvals.set_state(
            self.paths, self.store, chosen, approvals.APPROVED, risk_class="high"
        )
        return chosen


class TestTheChoiceConstrainsTheLanes(ProviderCase):
    def test_claude_only_never_plans_an_openrouter_lane(self) -> None:
        with self.openrouter_usable():
            self.approve_openrouter()
            plan = self.plan("claude")
        self.assertIsNotNone(plan.writer, plan.blocked_reason)
        self.assertEqual(plan.writer.lane, "claude_subscription")

    def test_openrouter_only_never_plans_the_subscription_lane(self) -> None:
        with self.openrouter_usable():
            chosen = self.approve_openrouter()
            plan = self.plan("openrouter")
        self.assertIsNotNone(plan.writer, plan.blocked_reason)
        self.assertEqual(plan.writer.lane, "openrouter")
        self.assertEqual(plan.writer.model, chosen)

    def test_auto_lets_both_lanes_compete(self) -> None:
        with self.openrouter_usable():
            self.approve_openrouter()
            plan = self.plan("auto")
        self.assertIsNotNone(plan.writer, plan.blocked_reason)
        self.assertIn(plan.writer.lane, ("claude_subscription", "openrouter"))

    def test_the_excluded_lane_is_named_in_the_rejections(self) -> None:
        with self.openrouter_usable():
            plan = self.plan("claude")
        self.assertTrue(
            any("provider is set to claude" in r for r in plan.rejections),
            plan.rejections,
        )


class TestWhenTheChoiceCannotRun(ProviderCase):
    def test_openrouter_selected_but_not_installed_blocks_rather_than_falling_back(
        self,
    ) -> None:
        """Silently running Claude instead would be the defect this fixes."""
        with self.openrouter_usable(installed=False):
            self.approve_openrouter()
            plan = self.plan("openrouter")
        self.assertIsNone(plan.writer)
        self.assertIsNotNone(plan.blocked_reason)

    def test_an_approved_model_on_an_uninstalled_harness_is_not_chosen(self) -> None:
        with self.openrouter_usable(installed=False):
            self.approve_openrouter()
            plan = self.plan("auto")
        self.assertIsNotNone(plan.writer, plan.blocked_reason)
        self.assertEqual(plan.writer.lane, "claude_subscription")

    def test_an_unapproved_model_is_not_chosen_even_when_the_harness_is_there(
        self,
    ) -> None:
        with self.openrouter_usable():
            plan = self.plan("openrouter")
        self.assertIsNone(plan.writer)

    def test_claude_selected_and_missing_blocks(self) -> None:
        with installed_harnesses(claude=False, opencode=True):
            plan = self.plan("claude")
        self.assertIsNone(plan.writer)


class TestWhatTheStatusSays(ProviderCase):
    def test_status_reports_the_lanes_the_choice_permits(self) -> None:
        self.assertEqual(
            local.provider_status({"provider": "openrouter"})["lanes"], ["openrouter"]
        )
        self.assertEqual(
            local.provider_status({"provider": "claude"})["lanes"],
            ["claude_subscription"],
        )

    def test_auto_reports_every_permitted_lane(self) -> None:
        status = local.provider_status({"provider": "auto"})
        self.assertEqual(status["provider"], "auto")
        self.assertEqual(
            sorted(status["lanes"]),
            ["claude_subscription", "codex_local", "openrouter"],
        )

    def test_auto_is_available_while_any_harness_is_installed(self) -> None:
        with installed_harnesses(claude=True, opencode=False, codex=False):
            self.assertEqual(
                local.provider_status({"provider": "auto"})["status"], "AVAILABLE"
            )

    def test_auto_is_available_later_when_nothing_is_installed(self) -> None:
        with installed_harnesses(claude=False, opencode=False, codex=False):
            self.assertEqual(
                local.provider_status({"provider": "auto"})["status"], "AVAILABLE_LATER"
            )

    def test_the_cli_accepts_the_auto_mode(self) -> None:
        self.assertIn("auto", local.PROVIDERS)


if __name__ == "__main__":
    unittest.main()
