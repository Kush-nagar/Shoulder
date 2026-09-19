"""Two harnesses, and the rules about which one runs what.

A non-Anthropic model must not be driven through Claude Code's Anthropic
compatibility endpoint: the harness is tuned for one family's tool protocol,
and judging DeepSeek or Qwen on someone else's scaffolding measures the
scaffolding. So OpenRouter models run in OpenCode, and the tests here are about
the boundary between the two -- which binary, which model id, which directory,
and what happens to the key.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from services.agentops import executors, localstate

BUDGET = {"max_turns": 25, "timeout_seconds": 600}


class ExecutorCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.paths = localstate.ensure(localstate.LocalPaths(self.root))
        self.worktree = self.root / "wt"
        self.worktree.mkdir()


class TestChoosingTheHarness(ExecutorCase):
    def test_the_subscription_lane_runs_claude_code(self) -> None:
        self.assertIsInstance(
            executors.for_lane("claude_subscription"), executors.ClaudeCliExecutor
        )

    def test_the_openrouter_lane_runs_a_model_neutral_harness(self) -> None:
        self.assertIsInstance(
            executors.for_lane("openrouter"), executors.OpenCodeExecutor
        )

    def test_an_openrouter_model_never_goes_through_claude_code(self) -> None:
        executor = executors.for_lane("openrouter")
        argv = executor.argv("deepseek/deepseek-v3", "implement", self.worktree, BUDGET)
        self.assertNotIn("claude", argv[0])
        self.assertEqual(argv[0], executors.OPENCODE_BINARY)

    def test_the_openrouter_harness_needs_no_anthropic_compatibility_variables(
        self,
    ) -> None:
        with mock.patch.dict(os.environ, {executors.OPENROUTER_KEY_ENV: "sk-or-x"}):
            env = executors.OpenCodeExecutor().env({}, self.root)
        self.assertNotIn("ANTHROPIC_BASE_URL", env)
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", env)


class TestTheOpenCodeCommandLine(ExecutorCase):
    def setUp(self) -> None:
        super().setUp()
        self.executor = executors.OpenCodeExecutor()

    def test_the_selected_model_reaches_the_invocation(self) -> None:
        argv = self.executor.argv(
            "moonshotai/kimi-k2", "implement", self.worktree, BUDGET
        )
        self.assertEqual(
            argv[argv.index("--model") + 1], "openrouter/moonshotai/kimi-k2"
        )

    def test_an_already_prefixed_model_is_not_prefixed_twice(self) -> None:
        self.assertEqual(
            self.executor.model_slug("openrouter/qwen/qwen3-coder"),
            "openrouter/qwen/qwen3-coder",
        )

    def test_the_isolated_worktree_is_the_working_directory(self) -> None:
        argv = self.executor.argv(
            "deepseek/deepseek-v3", "implement", self.worktree, BUDGET
        )
        self.assertEqual(argv[argv.index("--dir") + 1], str(self.worktree))

    def test_structured_output_is_requested(self) -> None:
        argv = self.executor.argv(
            "deepseek/deepseek-v3", "implement", self.worktree, BUDGET
        )
        self.assertEqual(argv[argv.index("--format") + 1], "json")

    def test_it_runs_non_interactively(self) -> None:
        argv = self.executor.argv(
            "deepseek/deepseek-v3", "implement", self.worktree, BUDGET
        )
        self.assertEqual(argv[1], "run")
        self.assertIn("--auto", argv)

    def test_the_prompt_arrives_on_stdin_rather_than_in_the_command(self) -> None:
        """It used to be the last argument, and a real review prompt is too
        big for one: Windows caps a command line at 32767 characters, so Task
        17's reviewer was refused the spawn outright with WinError 206.

        Measured against OpenCode 1.18.31 rather than assumed: prompt on
        stdin, no message argument, answer returned, exit 0.
        """
        command = self.executor.command(
            "deepseek/deepseek-v3", "implement", self.worktree, BUDGET, "do the thing"
        )
        self.assertTrue(self.executor.prompt_on_stdin)
        self.assertNotIn("do the thing", command)


class TestOpenCodePermissions(ExecutorCase):
    def test_a_writer_may_edit_and_run_commands(self) -> None:
        config = executors.OpenCodeExecutor().config("implement")
        self.assertEqual(config["permission"]["edit"], "allow")
        self.assertEqual(config["permission"]["bash"], "allow")

    def test_a_reviewer_may_not_edit(self) -> None:
        config = executors.OpenCodeExecutor().config("review")
        self.assertEqual(config["permission"]["edit"], "deny")

    def test_no_worker_may_reach_the_network_or_leave_its_worktree(self) -> None:
        config = executors.OpenCodeExecutor().config("implement")
        self.assertEqual(config["permission"]["webfetch"], "deny")
        self.assertEqual(config["permission"]["external_directory"], "deny")

    def test_the_config_is_written_outside_the_worktree(self) -> None:
        """Writing it into the worktree would show up in the diff under review."""
        run_dir = self.paths.run_dir("abc")
        path = executors.OpenCodeExecutor().write_config(run_dir, "implement")
        self.assertTrue(path.exists())
        self.assertNotIn(str(self.worktree), str(path))


class TestTheOpenRouterKey(ExecutorCase):
    def test_the_key_is_never_placed_in_argv(self) -> None:
        with mock.patch.dict(
            os.environ, {executors.OPENROUTER_KEY_ENV: "sk-or-secret"}
        ):
            command = executors.OpenCodeExecutor().command(
                "deepseek/deepseek-v3", "implement", self.worktree, BUDGET, "prompt"
            )
        self.assertNotIn("sk-or-secret", " ".join(command))

    def test_the_config_file_holds_a_substitution_not_the_key(self) -> None:
        with mock.patch.dict(
            os.environ, {executors.OPENROUTER_KEY_ENV: "sk-or-secret"}
        ):
            run_dir = self.paths.run_dir("abc")
            path = executors.OpenCodeExecutor().write_config(run_dir, "implement")
            written = path.read_text(encoding="utf-8")
        self.assertNotIn("sk-or-secret", written)
        self.assertIn("{env:OPENROUTER_API_KEY}", written)

    def test_the_key_reaches_the_child_environment_and_nowhere_else(self) -> None:
        with mock.patch.dict(
            os.environ, {executors.OPENROUTER_KEY_ENV: "sk-or-secret"}
        ):
            env = executors.OpenCodeExecutor().env({}, self.root)
        self.assertEqual(env[executors.OPENROUTER_KEY_ENV], "sk-or-secret")

    def test_without_a_key_the_harness_refuses_rather_than_running_anonymously(
        self,
    ) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                executors.OpenCodeExecutor().env({}, self.root)

    def test_a_claude_worker_never_inherits_the_openrouter_key(self) -> None:
        """A writable worker can read its own environment, so another lane's
        credential must not be in it."""
        with mock.patch.dict(
            os.environ,
            {executors.OPENROUTER_KEY_ENV: "sk-or-secret", "PATH": "/usr/bin"},
        ):
            env = executors.ClaudeCliExecutor().env(os.environ, self.root)
        self.assertNotIn(executors.OPENROUTER_KEY_ENV, env)
        self.assertNotIn("sk-or-secret", "".join(env.values()))
        self.assertEqual(env["PATH"], "/usr/bin")

    def test_a_claude_worker_does_not_inherit_a_redirected_endpoint(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "ANTHROPIC_BASE_URL": "https://openrouter.ai/api",
                "ANTHROPIC_AUTH_TOKEN": "sk-or-secret",
            },
        ):
            env = executors.ClaudeCliExecutor().env(os.environ, self.root)
        self.assertNotIn("ANTHROPIC_BASE_URL", env)
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", env)

    def test_the_openrouter_harness_still_receives_its_own_key(self) -> None:
        with mock.patch.dict(
            os.environ, {executors.OPENROUTER_KEY_ENV: "sk-or-secret"}
        ):
            env = executors.OpenCodeExecutor().env(os.environ, self.root)
        self.assertEqual(env[executors.OPENROUTER_KEY_ENV], "sk-or-secret")


class TestAvailability(ExecutorCase):
    def test_a_missing_key_disables_openrouter_cleanly(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(shutil, "which", return_value="/bin/opencode"):
                ok, reason = executors.OpenCodeExecutor().available()
        self.assertFalse(ok)
        self.assertIn(executors.OPENROUTER_KEY_ENV, reason)

    def test_a_missing_harness_names_the_one_time_install(self) -> None:
        with mock.patch.object(shutil, "which", return_value=None):
            ok, reason = executors.OpenCodeExecutor().available()
        self.assertFalse(ok)
        self.assertIn("npm install -g opencode-ai", reason)

    def test_native_claude_stays_available_when_openrouter_is_not(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            report = executors.availability()
        self.assertEqual(report["opencode"]["status"], "AVAILABLE_LATER")
        self.assertIn("claude-cli", report)

    def test_an_unavailable_harness_fails_the_run_rather_than_starting_one(
        self,
    ) -> None:
        """No launcher is injected here on purpose: this is the real path, and
        it must refuse before it reaches a process."""
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(shutil, "which", return_value=None):
                with mock.patch.object(subprocess, "Popen") as spawn:
                    result = executors.run(
                        executors.OpenCodeExecutor(),
                        self.paths,
                        prompt="p",
                        model="deepseek/deepseek-v3",
                        role="implement",
                        worktree=self.worktree,
                        budget=BUDGET,
                    )
        spawn.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertEqual(result["outcome"], "harness_unavailable")

    def test_an_injected_launcher_is_the_harness_and_is_not_probed(self) -> None:
        """A caller that supplies the launcher has supplied the harness, so
        the run must not depend on what is installed on the machine."""
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(shutil, "which", return_value=None):
                result = executors.run(
                    executors.ClaudeCliExecutor(),
                    self.paths,
                    prompt="p",
                    model="claude-sonnet-5",
                    role="implement",
                    worktree=self.worktree,
                    budget=BUDGET,
                    popen=lambda *a, **k: FakeProcess(
                        [json.dumps({"type": "result", "subtype": "success"})]
                    ),
                )
        self.assertTrue(result["ok"])


class FakeProcess:
    def __init__(self, lines: list[str], returncode: int = 0) -> None:
        self.stdout = iter(lines)
        self.stderr = None
        self.returncode = returncode
        self.pid = 4242

    def kill(self) -> None:
        self.returncode = -9

    def communicate(self, timeout: int | None = None) -> tuple[str, str]:
        return "", ""


class TestReadingWhatCameBack(ExecutorCase):
    def run_with(self, lines: list[str], returncode: int = 0) -> dict[str, Any]:
        self.seen: dict[str, Any] = {}

        def popen(command, **kwargs):  # type: ignore[no-untyped-def]
            self.seen = {"command": command, **kwargs}
            return FakeProcess(lines, returncode)

        with mock.patch.dict(os.environ, {executors.OPENROUTER_KEY_ENV: "sk-or-x"}):
            with mock.patch.object(shutil, "which", return_value="/bin/opencode"):
                return executors.run(
                    executors.OpenCodeExecutor(),
                    self.paths,
                    prompt="p",
                    model="deepseek/deepseek-v3",
                    role="implement",
                    worktree=self.worktree,
                    budget=BUDGET,
                    popen=popen,
                )

    def test_json_lines_are_captured_as_events(self) -> None:
        run = self.run_with(
            [
                json.dumps({"type": "message", "text": "editing app.py"}),
                json.dumps({"type": "result", "status": "completed"}),
            ]
        )
        self.assertTrue(run["ok"])
        self.assertEqual(run["last_action"], "editing app.py")

    def test_a_single_json_document_is_also_understood(self) -> None:
        """OpenCode does not publish its event schema, so the reader accepts
        the shapes it might reasonably use rather than failing the run."""
        events = executors.parse_events(
            [json.dumps({"type": "result", "status": "ok"})]
        )
        self.assertEqual(len(events), 1)

    def test_an_array_of_events_is_also_understood(self) -> None:
        events = executors.parse_events(
            [json.dumps([{"type": "message"}, {"type": "result"}])]
        )
        self.assertEqual(len(events), 2)

    def test_prose_output_does_not_crash_the_reader(self) -> None:
        self.assertEqual(executors.parse_events(["not json at all"]), [])

    def test_a_non_zero_exit_is_classified_as_a_failure(self) -> None:
        run = self.run_with([json.dumps({"type": "result"})], returncode=2)
        self.assertFalse(run["ok"])
        self.assertEqual(run["outcome"], "failed")

    def test_the_process_id_is_reported_for_recovery(self) -> None:
        run = self.run_with([json.dumps({"type": "result", "status": "ok"})])
        self.assertEqual(run["pid"], 4242)

    def test_the_worker_runs_in_its_worktree(self) -> None:
        self.run_with([json.dumps({"type": "result", "status": "ok"})])
        self.assertEqual(self.seen["cwd"], str(self.worktree))

    def test_openrouter_cost_is_reported_as_real_money(self) -> None:
        run = self.run_with(
            [json.dumps({"type": "result", "status": "ok", "cost_usd": 0.0123})]
        )
        self.assertEqual(run["cost_usd"], 0.0123)
        self.assertTrue(run["cost_known"])

    def test_subscription_cost_is_never_reported_as_billed(self) -> None:
        """The Claude figure is notional; calling it money would invent one."""

        def popen(command, **kwargs):  # type: ignore[no-untyped-def]
            return FakeProcess(
                [
                    json.dumps(
                        {"type": "result", "subtype": "success", "total_cost_usd": 0.5}
                    )
                ]
            )

        with mock.patch.object(shutil, "which", return_value="/bin/claude"):
            run = executors.run(
                executors.ClaudeCliExecutor(),
                self.paths,
                prompt="p",
                model="claude-sonnet-5",
                role="implement",
                worktree=self.worktree,
                budget=BUDGET,
                popen=popen,
            )
        self.assertEqual(run["cost_usd"], 0.5)
        self.assertFalse(run["cost_known"])

    def test_a_secret_never_reaches_the_run_log(self) -> None:
        leak = json.dumps({"type": "message", "text": "used sk-or-leaky-value"})
        with mock.patch.dict(
            os.environ, {executors.OPENROUTER_KEY_ENV: "sk-or-leaky-value"}
        ):
            with mock.patch.object(shutil, "which", return_value="/bin/opencode"):
                run = executors.run(
                    executors.OpenCodeExecutor(),
                    self.paths,
                    prompt="p",
                    model="deepseek/deepseek-v3",
                    role="implement",
                    worktree=self.worktree,
                    budget=BUDGET,
                    popen=lambda *a, **k: FakeProcess(
                        [leak, json.dumps({"type": "result", "status": "ok"})]
                    ),
                )
            recorded = Path(run["stream"]).read_text(encoding="utf-8")
        self.assertNotIn("sk-or-leaky-value", recorded)

    def test_redaction_still_applies_after_the_environment_changes(self) -> None:
        """A key set after a run started must still be scrubbed on the way out."""
        localstate.append_event(self.paths, "note", text="value sk-or-later-key")
        with mock.patch.dict(
            os.environ, {executors.OPENROUTER_KEY_ENV: "sk-or-later-key"}
        ):
            scrubbed = localstate.redact(
                {"events": localstate.events(self.paths, limit=5)}
            )
        self.assertNotIn("sk-or-later-key", json.dumps(scrubbed))


class TestThePermissionSplit(ExecutorCase):
    """Who may write, and what a writable worker is allowed to run.

    The two halves are not symmetric. A reviewer is confined by plan mode, and
    that is the whole point of it. A writable worker is unattended, and
    `acceptEdits` confines it in a way nobody intended: edits are approved,
    every shell command is not, and with no prompt surface `uv`, `pnpm`,
    `alembic`, `pytest` and `scripts/check.ps1` are simply denied. A worker
    that can edit but cannot test is worse than one that can do neither,
    because its output looks finished.
    """

    WRITABLE = ("implement", "repair")

    def argv(self, role: str) -> list[str]:
        return executors.ClaudeCliExecutor().argv(
            "claude-opus-5", role, self.worktree, BUDGET
        )

    def test_a_writable_worker_runs_in_bypass_mode(self) -> None:
        for role in self.WRITABLE:
            with self.subTest(role=role):
                self.assertIn("--dangerously-skip-permissions", self.argv(role))

    def test_a_writable_worker_never_merely_accepts_edits(self) -> None:
        for role in self.WRITABLE:
            with self.subTest(role=role):
                self.assertNotIn("acceptEdits", self.argv(role))

    def test_a_writable_worker_depends_on_no_prompt_surface(self) -> None:
        """Bypass replaces the prompt question rather than suppressing it, so
        the prompt flags are gone from the writable path entirely."""
        for role in self.WRITABLE:
            with self.subTest(role=role):
                argv = self.argv(role)
                self.assertNotIn("--permission-mode", argv)
                self.assertNotIn("--permission-prompts", argv)

    def test_a_reviewer_is_never_given_bypass(self) -> None:
        self.assertNotIn("--dangerously-skip-permissions", self.argv("review"))

    def test_no_read_only_role_is_given_bypass(self) -> None:
        for role in executors.READ_ONLY_ROLES:
            with self.subTest(role=role):
                self.assertNotIn("--dangerously-skip-permissions", self.argv(role))

    def test_read_only_roles_stay_in_plan_mode(self) -> None:
        for role in executors.READ_ONLY_ROLES:
            with self.subTest(role=role):
                argv = self.argv(role)
                self.assertEqual(argv[argv.index("--permission-mode") + 1], "plan")
                self.assertEqual(argv[argv.index("--permission-prompts") + 1], "none")

    def test_scout_is_read_only(self) -> None:
        self.assertIn("scout", executors.READ_ONLY_ROLES)
        self.assertNotIn("--dangerously-skip-permissions", self.argv("scout"))

    def test_the_worker_stays_non_interactive(self) -> None:
        """Bypass removes the approval question, not the headless contract."""
        for role in (*self.WRITABLE, *executors.READ_ONLY_ROLES):
            with self.subTest(role=role):
                argv = self.argv(role)
                self.assertIn("-p", argv)
                self.assertEqual(argv[argv.index("--output-format") + 1], "stream-json")
                self.assertIn("--verbose", argv)
                self.assertEqual(argv[argv.index("--model") + 1], "claude-opus-5")
                self.assertEqual(
                    argv[argv.index("--max-turns") + 1], str(BUDGET["max_turns"])
                )

    def test_the_openrouter_harness_is_untouched_by_the_split(self) -> None:
        """Bypass is a Claude Code flag. OpenCode keeps its own permission
        config, which is where a non-Anthropic worker's limits live."""
        for role in (*self.WRITABLE, *executors.READ_ONLY_ROLES):
            with self.subTest(role=role):
                argv = executors.OpenCodeExecutor().argv(
                    "deepseek/deepseek-v3", role, self.worktree, BUDGET
                )
                self.assertNotIn("--dangerously-skip-permissions", argv)
                self.assertNotIn("--permission-mode", argv)
                self.assertIn("--auto", argv)


class TestRecoveryAcrossHarnesses(ExecutorCase):
    def test_each_harness_knows_its_own_process_image(self) -> None:
        self.assertIn("claude", executors.worker_image(executors.ClaudeCliExecutor()))
        self.assertIn("opencode", executors.worker_image(executors.OpenCodeExecutor()))

    def test_an_interrupted_opencode_worker_is_recognised_as_gone(self) -> None:
        self.assertFalse(
            localstate.process_alive(
                999_999, executors.worker_image(executors.OpenCodeExecutor())
            )
        )


if __name__ == "__main__":
    unittest.main()
