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

    def test_the_prompt_is_the_last_argument(self) -> None:
        command = self.executor.command(
            "deepseek/deepseek-v3", "implement", self.worktree, BUDGET, "do the thing"
        )
        self.assertEqual(command[-1], "do the thing")


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

    def test_claude_code_never_reads_an_openrouter_key(self) -> None:
        source = Path(executors.__file__).read_text(encoding="utf-8")
        claude = source[
            source.index("class ClaudeCliExecutor") : source.index(
                "class OpenCodeExecutor"
            )
        ]
        self.assertNotIn("OPENROUTER", claude)


class TestReadOnlyRolesCannotWrite(ExecutorCase):
    def test_a_reviewer_runs_in_a_mode_that_cannot_edit(self) -> None:
        argv = executors.ClaudeCliExecutor().argv(
            "claude-sonnet-5", "review", self.worktree, BUDGET
        )
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "plan")

    def test_the_smoke_role_can_write(self) -> None:
        """A dry run and a model evaluation both prove a worker can change a
        file, so they must not be given a read-only mode. This is the bug the
        first dry run after the review change walked into."""
        self.assertNotIn("smoke", executors.READ_ONLY_ROLES)
        argv = executors.ClaudeCliExecutor().argv(
            "claude-haiku-4.5", "smoke", self.worktree, BUDGET
        )
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "acceptEdits")

    def test_an_opencode_smoke_worker_may_edit(self) -> None:
        config = executors.OpenCodeExecutor().config("smoke")
        self.assertEqual(config["permission"]["edit"], "allow")


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
                with mock.patch.object(executors.subprocess, "Popen") as spawn:
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
