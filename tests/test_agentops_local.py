"""The local execution layer.

What is asserted here is the part that can go quietly wrong: a worker running
in the wrong directory, a routed model that never reaches the process, a
provider key that ends up in a file, a writable worker left without the
shell access its own verification needs, or a recovery sweep that throws away
an interrupted worker's half-finished implementation.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest import mock

from agentops_fixtures import REPO_ROOT, installed_harnesses

from services.agentops import executors, local, localstate, state


def git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )


class LocalCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir(parents=True)
        self.paths = localstate.ensure(localstate.LocalPaths(self.root))
        self.config = localstate.load_config(self.paths)
        self.config["worktree_root"] = str(Path(self.tmp.name) / "agents")
        self.worktree = Path(self.tmp.name) / "agents" / "wt"
        self.worktree.mkdir(parents=True)
        self.enterContext(installed_harnesses(claude=True, opencode=False))


class TestTheExecutorCommandLine(LocalCase):
    def test_the_routed_model_reaches_the_process(self) -> None:
        argv = local.executor_argv(
            "claude-sonnet-5", "implement", self.worktree, self.config
        )
        self.assertEqual(argv[argv.index("--model") + 1], "claude-sonnet-5")

    def test_stream_json_is_asked_for_with_the_verbose_flag_it_requires(self) -> None:
        """The installed CLI refuses stream-json under --print without it."""
        argv = local.executor_argv(
            "claude-opus-5", "implement", self.worktree, self.config
        )
        self.assertIn("--verbose", argv)
        self.assertEqual(argv[argv.index("--output-format") + 1], "stream-json")

    def test_the_role_turn_budget_is_applied(self) -> None:
        self.config["roles"]["review"]["max_turns"] = 7
        argv = local.executor_argv(
            "claude-sonnet-5", "review", self.worktree, self.config
        )
        self.assertEqual(argv[argv.index("--max-turns") + 1], "7")

    def test_the_throwaway_roles_are_not_read_only(self) -> None:
        """A dry run writes a marker file; a read-only mode makes it fail in a
        way that reads as a bad model rather than a bad role."""
        source = (REPO_ROOT / "services" / "agentops" / "local.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('role="smoke"', source)
        self.assertNotIn('role="summarize"', source)

    def test_roles_do_not_share_one_budget(self) -> None:
        implement = local.role_budget(self.config, "implement")
        scout = local.role_budget(self.config, "scout")
        self.assertGreater(implement["max_turns"], scout["max_turns"])
        self.assertGreater(implement["timeout_seconds"], scout["timeout_seconds"])

    def test_a_writable_worker_bypasses_permissions(self) -> None:
        """An unattended run has no prompt surface, so a writable worker that
        merely accepts edits cannot run `uv`, `pytest` or `scripts/check.ps1`:
        it edits what it can never verify."""
        argv = local.executor_argv(
            "claude-opus-5", "implement", self.worktree, self.config
        )
        self.assertIn("--dangerously-skip-permissions", argv)
        self.assertNotIn("acceptEdits", argv)
        self.assertNotIn("--permission-mode", argv)
        self.assertNotIn("--permission-prompts", argv)

    def test_no_lane_puts_a_real_review_prompt_on_the_command_line(self) -> None:
        """Windows caps a command line at 32767 characters.

        A review prompt carries the diff, so it passes that the moment the
        diff is real. Task 17's reviewer never started: its prompt went in
        argv, CreateProcess refused the spawn with "[WinError 206] The
        filename or extension is too long", and the whole project loop died
        with it. Every lane therefore has to keep the prompt off argv, which
        is what `prompt_on_stdin` is for.
        """
        prompt = "x" * 40_000
        for lane in ("claude_subscription", "openrouter", "codex_local"):
            executor = executors.for_lane(lane)
            command = executor.command(
                "claude-sonnet-5", "review", self.worktree, {"max_turns": 5}, prompt
            )
            with self.subTest(lane=lane):
                self.assertTrue(
                    getattr(executor, "prompt_on_stdin", False),
                    f"{lane} would pass the prompt as an argument",
                )
                self.assertNotIn(prompt, command)
                self.assertLess(len(" ".join(command)), 32_767)

    def test_the_prompt_is_never_placed_after_a_variadic_flag(self) -> None:
        """`--add-dir` takes a list, so a prompt after it is read as another
        directory: the worker then starts with no instructions and exits
        having done nothing, which reads as a bad model rather than a bad
        command line. The worktree is already the working directory."""
        argv = local.executor_argv(
            "claude-opus-5", "implement", self.worktree, self.config
        )
        self.assertNotIn("--add-dir", argv)
        self.assertEqual(argv[-2], "--max-turns")


class TestProviderSelection(LocalCase):
    def test_claude_is_the_default_provider(self) -> None:
        self.assertEqual(localstate.DEFAULT_CONFIG["provider"], "claude")
        self.assertEqual(local.provider_status(self.config)["status"], "AVAILABLE")

    def test_openrouter_without_a_key_is_available_later_not_broken(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            status = local.provider_status({"provider": "openrouter"})
        self.assertEqual(status["status"], "AVAILABLE_LATER")
        self.assertEqual(status["harness"], "opencode")

    def test_openrouter_needs_its_harness_installed_as_well_as_a_key(self) -> None:
        """A key with no OpenCode on PATH is still not something that can run."""
        with mock.patch.dict(os.environ, {local.OPENROUTER_KEY_ENV: "sk-or-live"}):
            with installed_harnesses(claude=True, opencode=False):
                status = local.provider_status({"provider": "openrouter"})
        self.assertEqual(status["status"], "AVAILABLE_LATER")
        self.assertIn("opencode-ai", status["reason"])

    def test_openrouter_is_available_with_both_the_key_and_the_harness(self) -> None:
        with mock.patch.dict(os.environ, {local.OPENROUTER_KEY_ENV: "sk-or-live"}):
            with installed_harnesses(claude=True, opencode=True):
                status = local.provider_status({"provider": "openrouter"})
        self.assertEqual(status["status"], "AVAILABLE")

    def test_an_unknown_provider_is_reported_rather_than_guessed(self) -> None:
        self.assertEqual(
            local.provider_status({"provider": "gemini"})["status"], "UNKNOWN"
        )


class TestTheChildEnvironment(LocalCase):
    def test_a_missing_openrouter_key_leaves_native_claude_working(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            env = local.child_env({"provider": "claude"}, {"PATH": "/usr/bin"})
        self.assertNotIn("ANTHROPIC_BASE_URL", env)
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", env)

    def test_the_openrouter_key_reaches_the_child_environment_only(self) -> None:
        with mock.patch.dict(os.environ, {local.OPENROUTER_KEY_ENV: "sk-or-live"}):
            env = local.child_env({"provider": "openrouter"}, {"PATH": "/usr/bin"})
        self.assertEqual(env[local.OPENROUTER_KEY_ENV], "sk-or-live")

    def test_openrouter_without_a_key_refuses_to_spawn_rather_than_run_anonymously(
        self,
    ) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                local.child_env({"provider": "openrouter"}, {})

    def test_the_key_is_read_from_the_environment_and_never_from_config(self) -> None:
        config = {"provider": "openrouter", "openrouter_api_key": "sk-from-config"}
        with mock.patch.dict(os.environ, {local.OPENROUTER_KEY_ENV: "sk-or-live"}):
            env = local.child_env(config, {})
        self.assertEqual(env[local.OPENROUTER_KEY_ENV], "sk-or-live")
        self.assertNotIn("sk-from-config", "".join(env.values()))


class TestSkillRouting(LocalCase):
    def test_an_implementer_is_pointed_at_the_implementation_capabilities(self) -> None:
        line = local.skill_line("implement")
        self.assertIn("test-driven-development", line)
        self.assertIn("ponytail", line)

    def test_a_reviewer_is_pointed_at_review_capabilities(self) -> None:
        self.assertIn("/code-review", local.skill_line("review"))

    def test_a_repair_run_adds_systematic_debugging(self) -> None:
        self.assertIn(
            "systematic-debugging", local.skill_line("implement", repairing=True)
        )

    def test_not_every_skill_is_named_on_every_worker(self) -> None:
        """Naming all of them is how a worker ends up using none of them."""
        self.assertNotIn("brainstorming", local.skill_line("implement"))
        self.assertNotIn("/code-review", local.skill_line("implement"))


class FakeProcess:
    """A headless CLI that emits a scripted stream and exits."""

    def __init__(self, lines: list[str], returncode: int = 0) -> None:
        self.stdout = iter(lines)
        self.stderr = None
        self.returncode = returncode
        self.killed = False
        self.pid = 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def communicate(self, timeout: int | None = None) -> tuple[str, str]:
        return "", ""


class SilentProcess:
    """A worker that says nothing and would run far past its deadline.

    The old read loop only checked the clock when a line arrived, so this is
    exactly the process that never timed out: it blocks in the iterator.
    """

    def __init__(self, seconds: float = 30) -> None:
        self.seconds = seconds
        self.returncode: int | None = None
        self.stderr = None
        self.pid = 4242
        self._killed = threading.Event()
        self.stdout = self._blocking_stream()

    def _blocking_stream(self) -> Iterator[str]:
        # Blocks until something kills us, like a real silent child.
        self._killed.wait(self.seconds)
        return
        yield ""  # pragma: no cover - never reached

    def kill(self) -> None:
        self._killed.set()
        self.returncode = -9

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        self._killed.set()
        if self.returncode is None:
            self.returncode = -9
        return "", ""


RESULT_LINE = (
    '{"type":"result","subtype":"success","stop_reason":"end_turn",'
    '"session_id":"abc","total_cost_usd":0.5,'
    '"usage":{"input_tokens":10,"output_tokens":4}}'
)
ASSISTANT_LINE = (
    '{"type":"assistant","message":{"content":'
    '[{"type":"text","text":"done the thing"}]}}'
)


class TestRunningAWorker(LocalCase):
    def spawn(self, lines: list[str], returncode: int = 0):  # type: ignore[no-untyped-def]
        self.seen: dict[str, object] = {}

        def popen(argv, **kwargs):  # type: ignore[no-untyped-def]
            self.seen = {"argv": argv, **kwargs}
            return FakeProcess(lines, returncode)

        return popen

    def test_a_clean_run_is_completed_and_carries_its_usage(self) -> None:
        run = local.run_worker(
            self.root,
            self.paths,
            prompt="do the thing",
            model="claude-sonnet-5",
            role="implement",
            worktree=self.worktree,
            config=self.config,
            popen=self.spawn([ASSISTANT_LINE, RESULT_LINE]),
        )
        self.assertTrue(run["ok"])
        self.assertEqual(run["outcome"], "completed")
        self.assertEqual(run["cost_usd"], 0.5)
        self.assertEqual(run["usage"]["input_tokens"], 10)
        self.assertEqual(run["last_action"], "done the thing")

    def test_a_verdict_longer_than_the_label_survives_whole(self) -> None:
        """Task 18's reviewer passed the branch and the task was blocked.

        A verdict is JSON, and it runs past the length a progress label is
        clipped to as soon as it carries one finding. Reading the verdict from
        that label meant reading half a JSON document, which parses as
        nothing, so a reviewed task was refused for having no verdict while
        the verdict sat complete in the stream file.
        """
        verdict = json.dumps(
            {
                "verdict": "pass",
                "summary": "player mobile flow scopes evidence per player",
                "findings": [
                    {
                        "severity": "minor",
                        "confidence": "medium",
                        "file": "apps/web/app/player/session.ts",
                        "line": 11,
                        "requirement": "auth failures stay distinguishable",
                        "repair": "x" * 400,
                    }
                ],
            }
        )
        line = json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": verdict}]},
            }
        )
        run = local.run_worker(
            self.root,
            self.paths,
            prompt="review",
            model="claude-sonnet-5",
            role="review",
            worktree=self.worktree,
            config=self.config,
            popen=self.spawn([line, RESULT_LINE]),
        )
        self.assertGreater(len(verdict), 400, "the fixture must exceed the label clip")
        self.assertLess(len(run["last_action"]), len(verdict))
        self.assertEqual(run["final_message"], verdict)
        self.assertEqual(json.loads(run["final_message"])["verdict"], "pass")

    def test_a_worker_runs_in_its_own_worktree(self) -> None:
        local.run_worker(
            self.root,
            self.paths,
            prompt="p",
            model="claude-sonnet-5",
            role="implement",
            worktree=self.worktree,
            config=self.config,
            popen=self.spawn([RESULT_LINE]),
        )
        self.assertEqual(self.seen["cwd"], str(self.worktree))

    def test_a_non_zero_exit_is_a_failure(self) -> None:
        run = local.run_worker(
            self.root,
            self.paths,
            prompt="p",
            model="claude-sonnet-5",
            role="implement",
            worktree=self.worktree,
            config=self.config,
            popen=self.spawn([ASSISTANT_LINE], returncode=1),
        )
        self.assertFalse(run["ok"])
        self.assertEqual(run["outcome"], "failed")

    def test_the_wall_clock_stops_a_worker_that_will_not_stop(self) -> None:
        """--max-turns is undocumented in the installed CLI, so the timeout is
        the bound that is actually relied on."""
        self.config["roles"]["implement"]["timeout_seconds"] = 1
        run = local.run_worker(
            self.root,
            self.paths,
            prompt="p",
            model="claude-sonnet-5",
            role="implement",
            worktree=self.worktree,
            config=self.config,
            popen=lambda *a, **k: SilentProcess(seconds=30),
        )
        self.assertEqual(run["outcome"], "timeout")
        self.assertFalse(run["ok"])

    def test_the_stream_is_recorded_for_the_run(self) -> None:
        run = local.run_worker(
            self.root,
            self.paths,
            prompt="p",
            model="claude-sonnet-5",
            role="implement",
            worktree=self.worktree,
            config=self.config,
            popen=self.spawn([ASSISTANT_LINE, RESULT_LINE]),
        )
        recorded = Path(run["stream"]).read_text(encoding="utf-8")
        self.assertIn("done the thing", recorded)

    def test_a_secret_never_reaches_the_run_log(self) -> None:
        leaky = (
            '{"type":"assistant","message":{"content":'
            '[{"type":"text","text":"key sk-or-leak-me"}]}}'
        )
        with mock.patch.dict(os.environ, {local.OPENROUTER_KEY_ENV: "sk-or-leak-me"}):
            run = local.run_worker(
                self.root,
                self.paths,
                prompt="p",
                model="claude-sonnet-5",
                role="implement",
                worktree=self.worktree,
                config=self.config,
                popen=self.spawn([leaky, RESULT_LINE]),
            )
            recorded = Path(run["stream"]).read_text(encoding="utf-8")
            events = self.paths.events.read_text(encoding="utf-8")
        self.assertNotIn("sk-or-leak-me", recorded)
        self.assertNotIn("sk-or-leak-me", events)


class TestWorktrees(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir(parents=True)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "t@example.com")
        git(self.root, "config", "user.name", "Test")
        (self.root / "README.md").write_text("hello\n", encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "first")
        self.paths = localstate.ensure(localstate.LocalPaths(self.root))
        self.config = localstate.load_config(self.paths)
        self.config["worktree_root"] = str(Path(self.tmp.name) / "agents")

    def test_each_task_gets_its_own_directory_on_its_own_branch(self) -> None:
        one = local.worktree_path(self.root, self.config, "task-a")
        two = local.worktree_path(self.root, self.config, "task-b")
        local.create_worktree(self.root, "task-a", one)
        local.create_worktree(self.root, "task-b", two)
        self.assertNotEqual(one, two)
        self.assertTrue((one / "README.md").exists())
        self.assertTrue((two / "README.md").exists())

    def test_a_worker_edit_does_not_touch_the_other_worktree(self) -> None:
        one = local.worktree_path(self.root, self.config, "task-a")
        two = local.worktree_path(self.root, self.config, "task-b")
        local.create_worktree(self.root, "task-a", one)
        local.create_worktree(self.root, "task-b", two)
        (one / "README.md").write_text("changed\n", encoding="utf-8")
        self.assertEqual((two / "README.md").read_text(encoding="utf-8"), "hello\n")

    def test_the_main_checkout_is_never_modified(self) -> None:
        path = local.worktree_path(self.root, self.config, "task-a")
        local.create_worktree(self.root, "task-a", path)
        (path / "README.md").write_text("changed\n", encoding="utf-8")
        self.assertEqual(
            (self.root / "README.md").read_text(encoding="utf-8"), "hello\n"
        )

    def test_an_existing_worktree_is_reused_not_recreated(self) -> None:
        """Recreating it would throw away an interrupted worker's work."""
        path = local.worktree_path(self.root, self.config, "task-a")
        local.create_worktree(self.root, "task-a", path)
        (path / "partial.py").write_text("half done\n", encoding="utf-8")
        again = local.create_worktree(self.root, "task-a", path)
        self.assertFalse(again["created"])
        self.assertTrue((path / "partial.py").exists())

    def test_worktrees_live_outside_the_repository(self) -> None:
        path = local.worktree_path(self.root, {}, "task-a")
        self.assertNotIn(self.root.resolve(), list(path.resolve().parents))

    def test_removing_a_worktree_leaves_the_repository_intact(self) -> None:
        path = local.worktree_path(self.root, self.config, "task-a")
        local.create_worktree(self.root, "task-a", path)
        local.remove_worktree(self.root, path)
        self.assertFalse(path.exists())
        self.assertTrue((self.root / "README.md").exists())


class LoopCase(unittest.TestCase):
    """A repository just real enough for the coordinator to make a decision."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "repo"
        (self.root / "ops" / "state").mkdir(parents=True)
        (self.root / "docs").mkdir(parents=True)
        shutil.copy(
            REPO_ROOT / "ops" / "policy.json", self.root / "ops" / "policy.json"
        )
        shutil.copy(
            REPO_ROOT / "docs" / "06-tasks.md", self.root / "docs" / "06-tasks.md"
        )
        (self.root / "docs" / "projects").mkdir(parents=True)
        shutil.copy(
            REPO_ROOT / "docs" / "projects" / "README.md",
            self.root / "docs" / "projects" / "README.md",
        )
        for name in ("models.json", "providers.json", "budget.json", "progress.json"):
            shutil.copy(
                REPO_ROOT / "ops" / "state" / name, self.root / "ops" / "state" / name
            )
        self.tracked_tasks = self.root / "ops" / "state" / "tasks.json"
        self.tracked_tasks.write_text(
            json.dumps({"leases": {}}, indent=2), encoding="utf-8"
        )
        self.paths = localstate.ensure(localstate.LocalPaths(self.root))
        config = localstate.load_config(self.paths)
        config["worktree_root"] = str(Path(self.tmp.name) / "agents")
        localstate.save_config(self.paths, config)

    def policy_with_autonomy(self, enabled: bool = True) -> None:
        path = self.root / "ops" / "policy.json"
        policy = json.loads(path.read_text(encoding="utf-8"))
        policy["autonomy"]["enabled"] = enabled
        path.write_text(json.dumps(policy, indent=2), encoding="utf-8")


class TestTheRunLoopRefusesBeforeItStarts(LoopCase):
    def test_nothing_is_dispatched_without_explicit_local_intent(self) -> None:
        """Cloud autonomy is a different permission with a different blast
        radius. Local execution has its own switch, and it starts off."""
        result = local.run_once(self.root, self.paths)
        self.assertFalse(result["dispatched"])
        self.assertIn("local execution is not enabled", result["reason"])

    def test_refusing_starts_no_worker_and_no_worktree(self) -> None:
        calls: list[object] = []
        local.run_once(self.root, self.paths, popen=lambda *a, **k: calls.append(a))
        self.assertEqual(calls, [])
        self.assertEqual(localstate.worker_records(self.paths), {})


class TestTheWriterCap(LoopCase):
    def test_the_cap_comes_from_policy_and_is_enforced(self) -> None:
        """A writer past the cap is refused by the existing lease module.

        The cap is filled from policy rather than assumed to be one: it was
        raised to three on 2026-09-19, and a test that hard-codes the old
        number stops testing the ceiling and starts testing the constant.
        """
        local.enable_local(self.paths, by="test")
        self.enterContext(installed_harnesses(claude=True, opencode=False))
        cap = int(
            state.load_policy(state.Paths(self.root))["autonomy"][
                "max_parallel_writers"
            ]
        )
        localstate.write(
            self.paths.leases,
            {
                "leases": {
                    str(90 + index): {
                        "task_id": 90 + index,
                        "owner": f"someone-else-{index}",
                        "branch": f"block-{90 + index}",
                        "state": "implementing",
                        "heartbeat_at": localstate.now(),
                        "attempts": 1,
                    }
                    for index in range(cap)
                }
            },
        )
        result = local.run_once(self.root, self.paths)
        self.assertFalse(result["dispatched"])
        self.assertIn(f"max_parallel_writers={cap}", result["reason"])

    def test_the_cap_is_read_rather_than_hardcoded(self) -> None:
        """The runtime must keep working unchanged when the value becomes 2."""
        source = (REPO_ROOT / "services" / "agentops" / "local.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("max_parallel_writers", source)


class TestTrackedStateIsNeverWritten(LoopCase):
    def test_the_tracked_lease_ledger_is_untouched(self) -> None:
        before = self.tracked_tasks.read_text(encoding="utf-8")
        local.load_leases(self.root, self.paths)
        local.run_once(self.root, self.paths)
        self.assertEqual(self.tracked_tasks.read_text(encoding="utf-8"), before)

    def test_local_leases_are_seeded_from_the_tracked_ledger_once(self) -> None:
        self.tracked_tasks.write_text(
            json.dumps({"leases": {"7": {"task_id": 7, "state": "review"}}}),
            encoding="utf-8",
        )
        seeded = local.load_leases(self.root, self.paths)
        self.assertIn("7", seeded["leases"])
        self.assertTrue(self.paths.leases.exists())

    def test_local_leases_win_over_the_tracked_ledger_afterwards(self) -> None:
        localstate.write(self.paths.leases, {"leases": {"1": {"task_id": 1}}})
        self.tracked_tasks.write_text(
            json.dumps({"leases": {"7": {"task_id": 7}}}), encoding="utf-8"
        )
        self.assertEqual(
            list(local.load_leases(self.root, self.paths)["leases"]), ["1"]
        )

    def test_runtime_state_lives_under_the_ignored_directory(self) -> None:
        self.assertIn(".agentops", str(self.paths.leases))
        self.assertIn(".agentops", str(self.paths.workers))
        self.assertIn(".agentops", str(self.paths.events))


class TestVerdicts(unittest.TestCase):
    def test_a_clean_run_that_verifies_is_complete(self) -> None:
        self.assertEqual(
            local.classify_outcome(
                {"ok": True, "outcome": "completed"}, {"ok": True}, []
            ),
            "completed",
        )

    def test_a_writer_that_changed_nothing_has_not_implemented(self) -> None:
        """Task 17: twenty-eight turns, a plan returned, and a clean worktree.

        The harness exited cheerfully, so the run was "ok". Verification then
        passed trivially -- an unchanged tree is whatever main already was --
        and the task reached review with an empty diff. The reviewer had
        nothing to read and the loop stopped on a task nobody had written.
        """
        self.assertEqual(
            local.classify_outcome(
                {"ok": True, "outcome": "completed"}, {"ok": True}, [], []
            ),
            "implementation_failed",
        )

    def test_a_writer_that_changed_something_is_judged_on_its_tests(self) -> None:
        self.assertEqual(
            local.classify_outcome(
                {"ok": True, "outcome": "completed"}, {"ok": True}, [], ["app.py"]
            ),
            "completed",
        )

    def test_an_empty_change_is_repairable_rather_than_terminal(self) -> None:
        """So the task goes back to a writer instead of stopping the loop."""
        self.assertIn("implementation_failed", local.REPAIRABLE)

    def test_governance_still_outranks_an_empty_change(self) -> None:
        self.assertEqual(
            local.classify_outcome(
                {"ok": True, "outcome": "completed"},
                {"ok": True},
                ["ops/policy.json"],
                [],
            ),
            "governance_refused",
        )

    def test_verification_failure_blocks_completion(self) -> None:
        self.assertEqual(
            local.classify_outcome(
                {"ok": True, "outcome": "completed"}, {"ok": False}, []
            ),
            "verification_failed",
        )

    def test_an_unverified_run_is_not_complete(self) -> None:
        self.assertEqual(
            local.classify_outcome({"ok": True, "outcome": "completed"}, None, []),
            "unverified",
        )

    def test_a_governance_violation_is_refused_even_when_everything_passes(
        self,
    ) -> None:
        """Passing tests are not the question being asked of that branch."""
        self.assertEqual(
            local.classify_outcome(
                {"ok": True, "outcome": "completed"}, {"ok": True}, ["ops/policy.json"]
            ),
            "governance_refused",
        )

    def test_a_timeout_is_its_own_outcome(self) -> None:
        self.assertEqual(
            local.classify_outcome({"ok": False, "outcome": "timeout"}, None, []),
            "timeout",
        )

    def test_a_failed_implementation_is_reported_as_such(self) -> None:
        self.assertEqual(
            local.classify_outcome({"ok": False, "outcome": "failed"}, None, []),
            "implementation_failed",
        )


class TestEscalationUsesTheExistingCeilings(LoopCase):
    def lease(self, ci_cycles: int = 0) -> dict[str, Any]:
        return {
            "leases": {
                "15": {
                    "task_id": 15,
                    "owner": "local",
                    "branch": "block-15",
                    "state": "implementing",
                    "heartbeat_at": localstate.now(),
                    "attempts": 1,
                    "ci_repair_cycles": ci_cycles,
                }
            }
        }

    def policy(self) -> dict[str, Any]:
        loaded: dict[str, Any] = json.loads(
            (self.root / "ops" / "policy.json").read_text(encoding="utf-8")
        )
        return loaded

    def test_a_failure_becomes_a_repair_within_the_ceiling(self) -> None:
        tasks = self.lease()
        result = local._finish(
            self.paths, tasks, self.policy(), 15, "verification_failed", once_key="r1"
        )
        self.assertEqual(result["lease_state"], "repairing")
        self.assertTrue(result["escalated"])

    def test_repairs_stop_at_the_policy_ceiling(self) -> None:
        ceiling = int(self.policy()["escalation"]["max_ci_repair_cycles"])
        tasks = self.lease(ci_cycles=ceiling)
        result = local._finish(
            self.paths, tasks, self.policy(), 15, "verification_failed", once_key="r2"
        )
        self.assertEqual(result["lease_state"], "blocked")
        self.assertFalse(result["escalated"])

    def test_a_refused_branch_is_blocked_rather_than_repaired(self) -> None:
        tasks = self.lease()
        result = local._finish(
            self.paths, tasks, self.policy(), 15, "governance_refused", once_key="r3"
        )
        self.assertEqual(result["lease_state"], "blocked")

    def test_a_finished_task_parks_as_ready_for_a_pull_request(self) -> None:
        tasks = self.lease()
        result = local._finish(
            self.paths, tasks, self.policy(), 15, "ready_for_pr", once_key="r4"
        )
        self.assertEqual(result["lease_state"], "ready_for_pr")


class TestVerificationRouting(LoopCase):
    def test_the_fast_gate_runs_without_taking_the_lock(self) -> None:
        commands: list[list[str]] = []

        def runner(command, **kwargs):  # type: ignore[no-untyped-def]
            commands.append(command)
            return mock.Mock(returncode=0, stdout="", stderr="")

        result = local.verify(
            self.root, self.paths, self.root, runner=runner, uv=Path("uv")
        )
        self.assertTrue(result["ok"])
        self.assertFalse(result["locked"])
        self.assertFalse((self.paths.locks / "infra.lock").exists())

    def test_the_gated_suite_is_serialised(self) -> None:
        def runner(command, **kwargs):  # type: ignore[no-untyped-def]
            self.assertTrue((self.paths.locks / "infra.lock").exists())
            return mock.Mock(returncode=0, stdout="", stderr="")

        result = local.verify(
            self.root, self.paths, self.root, kind="gated", runner=runner, uv=Path("uv")
        )
        self.assertTrue(result["locked"])
        self.assertFalse((self.paths.locks / "infra.lock").exists())

    def test_a_failing_check_is_reported_with_its_output(self) -> None:
        def runner(command, **kwargs):  # type: ignore[no-untyped-def]
            return mock.Mock(returncode=1, stdout="ruff: E501", stderr="")

        result = local.verify(
            self.root, self.paths, self.root, runner=runner, uv=Path("uv")
        )
        self.assertFalse(result["ok"])
        self.assertIn("ruff: E501", result["steps"][0]["tail"])

    def test_an_unknown_verification_kind_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            local.verify(
                self.root, self.paths, self.root, kind="everything", uv=Path("uv")
            )


class TestChangedPaths(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir(parents=True)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "t@example.com")
        git(self.root, "config", "user.name", "Test")
        (self.root / "README.md").write_text("hello\n", encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "first")

    def test_an_uncommitted_edit_counts(self) -> None:
        """A branch that only stages a guarded change at push time is the case
        the governance guard exists for."""
        (self.root / "ops").mkdir()
        (self.root / "ops" / "policy.json").write_text("{}", encoding="utf-8")
        changed = local.changed_paths(self.root, self.root)
        self.assertIn("ops/policy.json", changed)

    def test_a_clean_worktree_reports_nothing(self) -> None:
        self.assertEqual(local.changed_paths(self.root, self.root), [])


class TestRecovery(LoopCase):
    def worker(self, **fields: object) -> None:
        localstate.save_worker(self.paths, "15", {"task_id": 15, **fields})

    def test_a_worker_whose_process_is_gone_mid_phase_is_interrupted(self) -> None:
        wt = Path(self.tmp.name) / "agents" / "block-15"
        wt.mkdir(parents=True)
        self.worker(pid=999_999, phase="implementing", worktree=str(wt))
        report = local.recover(self.root, self.paths)
        self.assertEqual(report["workers"][0]["state"], "interrupted")

    def test_an_interrupted_worker_keeps_its_worktree(self) -> None:
        """Its partial implementation is in there; deleting it is the one
        unrecoverable move."""
        wt = Path(self.tmp.name) / "agents" / "block-15"
        wt.mkdir(parents=True)
        (wt / "partial.py").write_text("half\n", encoding="utf-8")
        self.worker(pid=999_999, phase="implementing", worktree=str(wt))
        local.recover(self.root, self.paths)
        self.assertTrue((wt / "partial.py").exists())

    def test_a_finished_worker_is_not_reported_as_interrupted(self) -> None:
        self.worker(pid=999_999, phase="completed", finished_at=localstate.now())
        report = local.recover(self.root, self.paths)
        self.assertEqual(report["workers"][0]["state"], "finished")

    def test_a_live_worker_is_left_alone(self) -> None:
        self.worker(pid=os.getpid(), phase="implementing", image=None)
        with mock.patch.object(localstate, "process_alive", return_value=True):
            report = local.recover(self.root, self.paths)
        self.assertEqual(report["workers"][0]["state"], "running")

    def test_recovery_records_what_it_found(self) -> None:
        self.worker(pid=999_999, phase="implementing")
        local.recover(self.root, self.paths)
        self.assertIn("recovery", [e["kind"] for e in localstate.events(self.paths)])

    def test_a_stale_lease_is_only_taken_from_a_process_that_stopped(self) -> None:
        """The check the runtime hands the lease module: a queued worker looks
        stale while being entirely alive, and taking its lease would put a
        second writer on its branch."""
        source = (REPO_ROOT / "services" / "agentops" / "local.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("owner_finished=lambda", source)
        self.assertIn("process_alive", source)


class TestFableIsNeverSelected(unittest.TestCase):
    def test_no_local_code_path_names_fable(self) -> None:
        """Preflight established it needs usage credits this account has not
        bought, so routing it would produce a worker that cannot start."""
        for name in ("local.py", "localstate.py", "toolchain.py"):
            source = (REPO_ROOT / "services" / "agentops" / name).read_text(
                encoding="utf-8"
            )
            self.assertNotIn("fable", source.lower(), name)

    def test_the_qualified_catalogue_decides_the_model_not_this_layer(self) -> None:
        source = (REPO_ROOT / "services" / "agentops" / "local.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("routing.select(", source)
        self.assertIn("assignment.harness_model", source)


class TestTheWorkerPidIsRecorded(LocalCase):
    def test_the_pid_is_recorded_while_the_process_still_exists(self) -> None:
        """Recovery asks whether the pid is alive. A record without one reads
        as gone, so a running worker would be called interrupted and its lease
        handed to a second writer on the same branch."""
        seen: list[int] = []

        def popen(argv, **kwargs):  # type: ignore[no-untyped-def]
            process = FakeProcess([RESULT_LINE])
            process.pid = 4242
            return process

        run = local.run_worker(
            self.root,
            self.paths,
            prompt="p",
            model="claude-sonnet-5",
            role="implement",
            worktree=self.worktree,
            config=self.config,
            popen=popen,
            on_spawn=seen.append,
        )
        self.assertEqual(seen, [4242])
        self.assertEqual(run["pid"], 4242)


class TestABlockedPlanIsNotRun(LoopCase):
    def test_a_plan_blocked_for_any_reason_dispatches_nothing(self) -> None:
        """A writer can be routed while the plan is still blocked -- no
        reviewer at all, for instance. Running it anyway would carry out work
        the planner had already refused."""
        local.enable_local(self.paths, by="test")
        blocked = mock.Mock(
            writer=mock.Mock(),
            reviewer=None,
            blocked_reason="no reviewer available",
            rejections=[],
            branch="block-05-t15",
        )
        with mock.patch("services.agentops.local.local_plan", return_value=blocked):
            result = local.run_once(self.root, self.paths)
        self.assertFalse(result["dispatched"])
        self.assertIn("reviewer", result["reason"])


class TestTheTaskBaseline(unittest.TestCase):
    """What a branch changed is measured from where it left main.

    The baseline used to be a snapshot: whatever HEAD was the first time a
    task ran, stored and thereafter only read. That holds inside one attempt
    and fails across them, because a worktree outlives the attempt that made
    it. Task 16 was picked up two days later with a baseline from before four
    merges, so the governance guard was shown every commit main had gained in
    between and refused the branch for editing `ops/policy.json` and
    `.github/workflows` -- neither of which its worker had touched.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = Path(self.tmp) / "repo"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.write("app.py", "start\n")
        self.git("add", "-A")
        self.commit("first")

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
            check=True,
        )

    def commit(self, message: str) -> str:
        self.git("-c", "user.email=a@b", "-c", "user.name=c", "commit", "-qm", message)
        return self.git("rev-parse", "HEAD").stdout.strip()

    def write(self, name: str, body: str) -> None:
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")

    def paths(self) -> localstate.LocalPaths:
        return localstate.ensure(localstate.LocalPaths(Path(self.tmp) / "state"))

    def test_it_is_where_the_branch_left_main(self) -> None:
        diverged = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("checkout", "-q", "-b", "task")
        self.write("app.py", "changed\n")
        self.git("add", "-A")
        self.commit("work")
        self.assertEqual(local.merge_base(self.repo), diverged)

    def test_it_does_not_move_as_the_branch_commits(self) -> None:
        diverged = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("checkout", "-q", "-b", "task")
        for n in range(3):
            self.write("app.py", f"change {n}\n")
            self.git("add", "-A")
            self.commit(f"work {n}")
            self.assertEqual(local.merge_base(self.repo), diverged)

    def test_it_does_not_move_as_main_moves_ahead(self) -> None:
        """The failure this replaced, stated directly.

        Main gaining commits must not make them look like the branch's work.
        """
        diverged = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("checkout", "-q", "-b", "task")
        self.write("app.py", "branch work\n")
        self.git("add", "-A")
        self.commit("branch work")

        self.git("checkout", "-q", "main")
        self.write("ops/policy.json", '{"autonomy": {}}\n')
        self.git("add", "-A")
        self.commit("policy change on main")
        self.git("checkout", "-q", "task")

        self.assertEqual(local.merge_base(self.repo), diverged)
        changed = local.changed_paths(self.repo, self.repo, base=diverged)
        self.assertNotIn("ops/policy.json", changed)
        self.assertIn("app.py", changed)

    def test_a_stale_recorded_baseline_is_not_believed(self) -> None:
        """The Task 16 refusal, reproduced and then not reproduced."""
        stale = self.git("rev-parse", "HEAD").stdout.strip()
        self.write("ops/policy.json", '{"autonomy": {}}\n')
        self.git("add", "-A")
        self.commit("policy change that lands on main")
        self.git("checkout", "-q", "-b", "task")
        self.write("app.py", "branch work\n")
        self.git("add", "-A")
        self.commit("branch work")

        paths = self.paths()
        localstate.save_worker(paths, "16", {"base_sha": stale})

        # Measured from the stale snapshot, the branch looks like it edited policy.
        self.assertIn(
            "ops/policy.json", local.changed_paths(self.repo, self.repo, base=stale)
        )

        base = local.task_baseline(paths, 16, worktree=self.repo)
        self.assertNotEqual(base, stale)
        self.assertNotIn(
            "ops/policy.json", local.changed_paths(self.repo, self.repo, base=base)
        )

    def test_the_corrected_baseline_is_written_back(self) -> None:
        stale = self.git("rev-parse", "HEAD").stdout.strip()
        self.write("app.py", "moved on\n")
        self.git("add", "-A")
        self.commit("main moves")
        self.git("checkout", "-q", "-b", "task")

        paths = self.paths()
        localstate.save_worker(paths, "16", {"base_sha": stale})
        base = local.task_baseline(paths, 16, worktree=self.repo)
        stored = localstate.worker_records(paths)["16"]["base_sha"]
        self.assertEqual(stored, base)
        self.assertNotEqual(stored, stale)

    def test_a_checkout_git_cannot_answer_for_keeps_what_was_recorded(self) -> None:
        """Losing the baseline entirely would measure the whole branch as new."""
        paths = self.paths()
        localstate.save_worker(paths, "16", {"base_sha": "recorded0"})
        nowhere = Path(self.tmp) / "not-a-repo"
        nowhere.mkdir()
        self.assertEqual(local.task_baseline(paths, 16, worktree=nowhere), "recorded0")


if __name__ == "__main__":
    unittest.main()
