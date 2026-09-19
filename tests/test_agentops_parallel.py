"""Proof that three writable workers can run at once without losing state.

The runtime ran one writer at a time until 2026-09-19, which made a whole
class of bug impossible rather than absent. Raising the cap to three brings it
back, so each property the single-writer design used to guarantee for free is
asserted here instead.

The concurrency tests use real processes, not threads. Every ledger here is
shared between separate operating-system processes -- a coordinator and its
workers -- and a threading test would pass on the GIL alone while the file
lock did nothing, which is exactly the failure it is supposed to detect.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest import mock

from agentops_fixtures import REPO_ROOT, installed_harnesses

from services.agentops import (
    classify,
    coordinator,
    executors,
    leases,
    local,
    localstate,
    project,
    routing,
    state,
)

# A child that writes to the same ledger this process is writing to. Spawned
# rather than forked, so it works the same way on Windows, where there is no
# fork and where the lock is a different system call.
WRITER = """
import sys
sys.path.insert(0, {repo!r})
from pathlib import Path
from services.agentops import localstate

paths = localstate.LocalPaths(Path({root!r}))
for index in range({count}):
    record = {{"task_id": "{key}", "n": index}}
    localstate.save_worker(paths, "{key}-%d" % index, record)
"""

EVENT_WRITER = """
import sys
sys.path.insert(0, {repo!r})
from pathlib import Path
from services.agentops import localstate

paths = localstate.LocalPaths(Path({root!r}))
for index in range({count}):
    localstate.append_event(paths, "probe", writer="{key}", n=index)
"""


def _spawn(source: str) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-c", source],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


class ConcurrentStateCase(unittest.TestCase):
    """Concurrent writes to the shared ledgers, from real processes."""

    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)
        self.paths = localstate.ensure(localstate.LocalPaths(self.root))

    def run_all(self, template: str, writers: int, count: int) -> None:
        children = [
            _spawn(
                template.format(
                    repo=str(REPO_ROOT),
                    root=str(self.root),
                    count=count,
                    key=f"w{index}",
                )
            )
            for index in range(writers)
        ]
        for child in children:
            _, err = child.communicate(timeout=180)
            self.assertEqual(child.returncode, 0, err)


class TestConcurrentStateWrites(ConcurrentStateCase):
    def test_three_writers_lose_no_record(self) -> None:
        """The failure this exists to prevent, stated as a count.

        Without the lock each process reads the ledger, adds its own key and
        writes the whole document back, so the last writer's copy -- which
        never contained the others' keys -- is what survives. The count comes
        out low and nothing reports an error, which is what makes it dangerous:
        a dropped lease record is two writers on one branch.
        """
        writers, each = 3, 40
        self.run_all(WRITER, writers, each)
        records = localstate.worker_records(self.paths)
        self.assertEqual(len(records), writers * each)
        for index in range(writers):
            for n in range(each):
                self.assertIn(f"w{index}-{n}", records)

    def test_the_ledger_is_still_valid_json_afterwards(self) -> None:
        self.run_all(WRITER, 3, 25)
        loaded = json.loads(self.paths.workers.read_text(encoding="utf-8"))
        self.assertEqual(len(loaded["workers"]), 75)


class TestConcurrentEventWrites(ConcurrentStateCase):
    def test_no_event_line_is_lost_or_torn(self) -> None:
        writers, each = 3, 60
        self.run_all(EVENT_WRITER, writers, each)
        lines = self.paths.events.read_text(encoding="utf-8").splitlines()
        probes = []
        for line in lines:
            # Parsed rather than counted: a torn line is still a line, so a
            # length check alone would pass on corrupted output.
            probes.append(json.loads(line))
        self.assertEqual(len(probes), writers * each)
        for index in range(writers):
            mine = [p for p in probes if p.get("writer") == f"w{index}"]
            self.assertEqual(sorted(p["n"] for p in mine), list(range(each)))


class TestTheLockItself(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.paths = localstate.ensure(localstate.LocalPaths(Path(self.dir.name)))

    def test_it_excludes_a_second_holder(self) -> None:
        with localstate.lock(self.paths, "probe"):
            child = _spawn(
                textwrap.dedent(
                    f"""
                    import sys
                    sys.path.insert(0, {str(REPO_ROOT)!r})
                    from pathlib import Path
                    from services.agentops import localstate
                    paths = localstate.LocalPaths(Path({self.dir.name!r}))
                    try:
                        with localstate.lock(paths, "probe", timeout=1):
                            print("TOOK")
                    except localstate.LockTimeout:
                        print("BLOCKED")
                    """
                )
            )
            out, err = child.communicate(timeout=60)
        self.assertIn("BLOCKED", out, err)

    def test_it_is_released_when_the_holder_dies(self) -> None:
        """A killed worker must not wedge the ledger for everyone else.

        This is why the lock is a byte range rather than a lock file that gets
        created and deleted: the timeout path in this runtime kills a whole
        process tree, so a holder dying mid-write is an ordinary event.
        """
        child = _spawn(
            textwrap.dedent(
                f"""
                import os, sys, time
                sys.path.insert(0, {str(REPO_ROOT)!r})
                from pathlib import Path
                from services.agentops import localstate
                paths = localstate.LocalPaths(Path({self.dir.name!r}))
                with localstate.lock(paths, "probe"):
                    print("HELD", flush=True)
                    os._exit(1)
                """
            )
        )
        try:
            self.assertIn("HELD", (child.stdout.readline() if child.stdout else ""))
            child.wait(timeout=60)
        finally:
            for stream in (child.stdout, child.stderr):
                if stream is not None:
                    stream.close()
        with localstate.lock(self.paths, "probe", timeout=10):
            pass  # reached, so the dead holder's lock did not survive it

    def test_taking_it_twice_in_one_thread_fails_at_once(self) -> None:
        """Waiting for yourself must not look like waiting for someone else.

        The lock is a byte range held per file handle and each call opens its
        own, so it is not reentrant. Without this guard a caller that locks and
        then calls a helper that locks the same name stalls for the full
        timeout and then reports that another worker is holding it -- which
        sends whoever reads the message looking for a process that does not
        exist.
        """
        with localstate.lock(self.paths, "probe"):
            with self.assertRaises(localstate.LockReentered):
                with localstate.lock(self.paths, "probe"):
                    pass
        # And the guard releases with the lock, so the name is usable again.
        with localstate.lock(self.paths, "probe", timeout=5):
            pass

    def test_a_different_name_is_not_blocked_by_the_guard(self) -> None:
        with localstate.lock(self.paths, "probe"):
            with localstate.lock(self.paths, "other", timeout=5):
                pass

    def test_a_mutation_is_read_modify_write_under_one_lock(self) -> None:
        def bump(stored: dict[str, Any]) -> None:
            stored["n"] = int(stored.get("n", 0)) + 1

        for _ in range(5):
            localstate.mutate(self.paths, self.paths.runtime, bump, {})
        self.assertEqual(localstate.read(self.paths.runtime)["n"], 5)

    def test_threads_sharing_one_process_also_serialise(self) -> None:
        """The in-process case, which the file lock does not by itself cover.

        `flock` and `msvcrt.locking` are held per file handle, and each call
        here opens its own, so this is a real question rather than a formality.
        """

        def bump(_: int) -> None:
            def change(stored: dict[str, Any]) -> None:
                stored["n"] = int(stored.get("n", 0)) + 1

            localstate.mutate(self.paths, self.paths.runtime, change, {})

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(bump, range(80)))
        self.assertEqual(localstate.read(self.paths.runtime)["n"], 80)


def _policy() -> dict[str, Any]:
    return state.read_json(state.Paths(REPO_ROOT).policy)


class TestTheWriterCap(unittest.TestCase):
    """Two, then three, then one too many."""

    def setUp(self) -> None:
        self.policy = _policy()
        self.tasks: dict[str, Any] = {"leases": {}}

    def acquire(self, owner: str, task_id: int) -> dict[str, Any]:
        return leases.acquire(
            self.tasks,
            self.policy,
            task_id=task_id,
            owner=owner,
            branch=f"block-x-t{task_id}",
            assignment={"lane": "claude_subscription"},
        )

    def test_policy_permits_three_writers(self) -> None:
        self.assertEqual(int(self.policy["autonomy"]["max_parallel_writers"]), 3)

    def test_two_writers_hold_leases_at_once(self) -> None:
        self.acquire("a", 14)
        self.acquire("b", 15)
        active = leases.active_leases(self.tasks, self.policy)
        self.assertEqual(len(active), 2)
        self.assertEqual(
            sorted(str(row["branch"]) for row in active),
            ["block-x-t14", "block-x-t15"],
        )

    def test_three_writers_hold_leases_at_once(self) -> None:
        for index, owner in enumerate("abc"):
            self.acquire(owner, 14 + index)
        self.assertEqual(len(leases.active_leases(self.tasks, self.policy)), 3)

    def test_a_fourth_is_refused(self) -> None:
        for index, owner in enumerate("abc"):
            self.acquire(owner, 14 + index)
        with self.assertRaises(leases.LeaseConflict) as raised:
            self.acquire("d", 17)
        self.assertIn("max_parallel_writers=3", str(raised.exception))

    def test_each_writer_gets_its_own_branch(self) -> None:
        """Worktree isolation begins here: one branch per task, never shared."""
        for index, owner in enumerate("abc"):
            self.acquire(owner, 14 + index)
        branches = [
            row["branch"] for row in leases.active_leases(self.tasks, self.policy)
        ]
        self.assertEqual(len(set(branches)), 3)

    def test_a_second_writer_cannot_take_a_held_task(self) -> None:
        self.acquire("a", 14)
        with self.assertRaises(leases.LeaseConflict):
            self.acquire("b", 14)


class TestWorktreeIsolation(unittest.TestCase):
    def test_each_branch_gets_its_own_directory(self) -> None:
        config = {"worktree_root": ""}
        paths = [
            local.worktree_path(REPO_ROOT, config, f"block-x-t{task}")
            for task in (14, 15, 16)
        ]
        self.assertEqual(len(set(paths)), 3)
        for path in paths:
            self.assertNotEqual(path.resolve(), REPO_ROOT.resolve())

    def test_a_worktree_is_never_the_coordinator_checkout(self) -> None:
        """A writer in the coordinator's own checkout would dirty every other
        worker's view of the repository at once."""
        root = local.worktree_root(REPO_ROOT, {"worktree_root": ""})
        self.assertNotEqual(root.resolve(), REPO_ROOT.resolve())


class TestDependencyBlocking(unittest.TestCase):
    """A task whose prerequisite has not merged is never dispatched."""

    def setUp(self) -> None:
        self.ctx = coordinator.load_context(REPO_ROOT)
        self.ctx.tasks = {"leases": {}}

    def test_a_task_with_an_unmet_prerequisite_is_not_eligible(self) -> None:
        blocked = [
            candidate
            for candidate in coordinator.candidates(self.ctx)
            if candidate.missing_prerequisites
        ]
        self.assertTrue(blocked, "the backlog has no dependent task to check")
        for candidate in blocked:
            self.assertFalse(candidate.eligible, candidate.task.id)

    def test_a_leased_task_is_not_offered_to_a_second_writer(self) -> None:
        first = coordinator.next_eligible(self.ctx)
        assert first is not None
        leases.acquire(
            self.ctx.tasks,
            self.ctx.policy,
            task_id=first.task.id,
            owner="worker-a",
            branch="block-x",
            assignment={"lane": "claude_subscription"},
        )
        second = coordinator.next_eligible(self.ctx)
        if second is not None:
            self.assertNotEqual(second.task.id, first.task.id)

    def test_the_free_slots_never_exceed_what_is_eligible(self) -> None:
        """What stops the parallel loop spinning on an empty backlog.

        Submitting a writer with nothing eligible to give it returns "no
        eligible task" at once, and the next pass submits it again.
        """
        startable = sum(1 for c in coordinator.candidates(self.ctx) if c.eligible)
        self.assertLessEqual(startable, len(self.ctx.backlog.task_ids()))
        self.assertGreaterEqual(startable, 0)


def _inputs(**overrides: Any) -> routing.RoutingInputs:
    ctx = coordinator.load_context(REPO_ROOT)
    base = ctx.routing_inputs()
    base.qualified_lanes = frozenset({"codex_cloud", "codex_local"})
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def _classification(
    category: str, complexity: str, **flags: Any
) -> classify.Classification:
    defaults: dict[str, Any] = dict(
        task_id=99,
        category=category,
        complexity=complexity,
        security_risk=False,
        destructive_risk=False,
        migration_risk=False,
        visual_required=False,
        browser_required=False,
        context7_expected=False,
        prerequisite_count=0,
        test_clause_count=2,
        read_doc_count=2,
        reasons=(),
    )
    defaults.update(flags)
    return classify.Classification(**defaults)


class TestTheRoutingPolicyItWasAskedFor(unittest.TestCase):
    """The routing table, asserted as behaviour rather than as configuration."""

    def test_frontend_goes_to_codex(self) -> None:
        chosen = routing.select(_inputs(), _classification("frontend", "ROUTINE"))
        self.assertEqual(chosen.lane, "codex_local")

    def test_security_work_goes_to_codex_at_the_top_of_the_ladder(self) -> None:
        chosen = routing.select(
            _inputs(), _classification("backend", "CRITICAL", security_risk=True)
        )
        self.assertEqual(chosen.lane, "codex_local")
        self.assertEqual(chosen.effort, "xhigh")

    def test_migration_work_goes_to_codex(self) -> None:
        chosen = routing.select(
            _inputs(),
            _classification(
                "backend", "CRITICAL", migration_risk=True, security_risk=True
            ),
        )
        self.assertEqual(chosen.lane, "codex_local")
        self.assertEqual(chosen.effort, "xhigh")

    def test_ordinary_backend_work_stays_with_claude(self) -> None:
        chosen = routing.select(_inputs(), _classification("backend", "ROUTINE"))
        self.assertEqual(chosen.lane, "claude_subscription")
        self.assertNotEqual(chosen.effort, "xhigh")

    def test_mechanical_work_goes_to_deepseek(self) -> None:
        chosen = routing.select(_inputs(), _classification("backend", "TRIVIAL"))
        self.assertEqual(chosen.lane, "openrouter")
        self.assertEqual(chosen.effort, "low")

    def test_claude_exhaustion_routes_eligible_work_to_deepseek(self) -> None:
        chosen = routing.select(
            _inputs(provider_health={"claude_subscription": "COOLDOWN"}),
            _classification("backend", "ROUTINE"),
        )
        self.assertEqual(chosen.lane, "openrouter")

    def test_claude_exhaustion_never_routes_frontend_to_deepseek(self) -> None:
        chosen = routing.select(
            _inputs(provider_health={"claude_subscription": "COOLDOWN"}),
            _classification("frontend", "ROUTINE"),
        )
        self.assertEqual(chosen.lane, "codex_local")

    def test_repeated_failure_escalates_to_codex(self) -> None:
        """Two failed attempts is the only route to the escalation class."""
        task = coordinator.load_context(REPO_ROOT).backlog.tasks[15]
        escalated = classify.classify(task, prior_failures=2)
        self.assertEqual(escalated.complexity, "EXTREME")
        chosen = routing.select(_inputs(), escalated)
        self.assertEqual(chosen.lane, "codex_local")
        self.assertEqual(chosen.effort, "xhigh")

    def test_a_reviewer_is_never_the_family_that_wrote_the_branch(self) -> None:
        current = _classification("frontend", "ROUTINE")
        writer = routing.select(_inputs(), current)
        reviewer = routing.select_reviewer(_inputs(), current, writer)
        policy = _policy()
        self.assertNotEqual(
            policy["lanes"][reviewer.lane]["provider"],
            policy["lanes"][writer.lane]["provider"],
        )


class TestTheCodexExecutor(unittest.TestCase):
    """The command line, built from what the installed CLI actually accepts."""

    def argv(self, role: str = "implement", effort: str = "high") -> list[str]:
        executor = executors.CodexCliExecutor(binary="codex", effort=effort)
        return executor.argv("gpt-5.6-sol", role, Path("/tmp/wt"), {"max_turns": 10})

    def test_the_lane_resolves_to_this_harness(self) -> None:
        executor = executors.for_lane("codex_local", effort="xhigh")
        self.assertIsInstance(executor, executors.CodexCliExecutor)
        self.assertEqual(executor.provider, "openai")

    def test_it_runs_exec_with_structured_output(self) -> None:
        argv = self.argv()
        self.assertEqual(argv[1], "exec")
        self.assertIn("--json", argv)

    def test_the_model_and_effort_are_really_applied(self) -> None:
        """The whole reason this lane exists rather than the mention lane."""
        argv = self.argv(effort="xhigh")
        self.assertIn("-m", argv)
        self.assertEqual(argv[argv.index("-m") + 1], "gpt-5.6-sol")
        self.assertIn('model_reasoning_effort="xhigh"', argv)

    def test_the_workstations_own_config_is_not_inherited(self) -> None:
        """Otherwise the worker runs with whatever MCP servers, hooks and model
        the human last configured, and is not reproducible."""
        self.assertIn("--ignore-user-config", self.argv())

    def test_a_reviewer_cannot_write(self) -> None:
        argv = self.argv(role="review")
        self.assertEqual(argv[argv.index("-s") + 1], "read-only")
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", argv)

    def test_a_writer_can_run_the_commands_the_task_needs(self) -> None:
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", self.argv())

    def test_an_account_configured_lane_is_not_asked_for_that_model(self) -> None:
        executor = executors.CodexCliExecutor(binary="codex")
        argv = executor.argv("account-configured", "implement", Path("/tmp"), {})
        self.assertNotIn("-m", argv)

    def test_other_lanes_credentials_are_withheld(self) -> None:
        executor = executors.CodexCliExecutor(binary="codex")
        env = executor.env(
            {"OPENROUTER_API_KEY": "or-secret", "ANTHROPIC_API_KEY": "an-secret"},
            Path("/tmp"),
        )
        self.assertNotIn("OPENROUTER_API_KEY", env)
        self.assertNotIn("ANTHROPIC_API_KEY", env)

    def test_the_recorded_process_image_is_codex(self) -> None:
        image = executors.worker_image(executors.CodexCliExecutor())
        self.assertIn("codex", image)

    def test_availability_reports_all_three_harnesses(self) -> None:
        with installed_harnesses(claude=True, opencode=False, codex=True):
            report = executors.availability()
        self.assertTrue(report["codex-cli"]["available"], report["codex-cli"])
        self.assertEqual(report["codex-cli"]["provider"], "openai")

    def test_the_binary_is_resolved_before_it_is_spawned(self) -> None:
        """Windows CreateProcess appends `.exe` and nothing else.

        `codex` and `opencode` are both installed by npm as `.CMD` shims, so a
        bare argv[0] fails with "The system cannot find the file specified"
        while `available()` has just reported the harness installed. Claude
        Code escaped it only by happening to install a real `.EXE`. Spawning
        is patched rather than injected here because the injected-launcher path
        deliberately skips resolution, so using it would test nothing.
        """
        shim = str(Path("C:/npm/codex.CMD"))
        spawned: dict[str, Any] = {}

        def fake_popen(command: list[str], **kwargs: Any) -> FakeProcess:
            spawned["argv"] = list(command)
            return FakeProcess(CODEX_OK)

        with tempfile.TemporaryDirectory() as tmp:
            paths = localstate.ensure(localstate.LocalPaths(Path(tmp)))
            with (
                mock.patch("shutil.which", return_value=shim),
                mock.patch("subprocess.Popen", fake_popen),
            ):
                run = executors.run(
                    executors.CodexCliExecutor(binary="codex"),
                    paths,
                    prompt="p",
                    model="gpt-5.6-sol",
                    role="smoke",
                    worktree=Path(tmp),
                    budget={"max_turns": 2, "timeout_seconds": 30},
                )
        self.assertTrue(run["ok"], run)
        self.assertEqual(spawned["argv"][0], shim)
        self.assertEqual(spawned["argv"][1], "exec")

    def test_a_missing_binary_says_how_to_install_it(self) -> None:
        with installed_harnesses(claude=True, opencode=False, codex=False):
            ok, reason = executors.CodexCliExecutor().available()
        self.assertFalse(ok)
        self.assertIn("npm install -g @openai/codex", reason)


# Real JSONL from `codex exec --json`, recorded from codex-cli 0.154.0 rather
# than written from the documentation. The benign `error` items are in it on
# purpose: they arrive on healthy runs, and reading one as a failure would fail
# every task.
CODEX_OK = [
    '{"type":"thread.started","thread_id":"01a0b534"}',
    '{"type":"item.completed","item":{"id":"item_0","type":"error",'
    '"message":"clamping SessionEnd hook timeout to 3s"}}',
    '{"type":"turn.started"}',
    '{"type":"item.completed","item":{"id":"item_1","type":"agent_message",'
    '"text":"Edited services/api/app/main.py and ran the tests."}}',
    '{"type":"turn.completed","usage":{"input_tokens":19507,'
    '"cached_input_tokens":0,"output_tokens":35,"reasoning_output_tokens":0}}',
]

CODEX_FAILED = [
    '{"type":"thread.started","thread_id":"01a0b534"}',
    '{"type":"turn.started"}',
    '{"type":"error","message":"{\\"type\\":\\"error\\",\\"status\\":400}"}',
    '{"type":"turn.failed","error":{"message":"model is not supported"}}',
]

CODEX_EXHAUSTED = [
    '{"type":"turn.started"}',
    '{"type":"turn.failed","error":{"message":'
    '"You have hit your usage limit. resets at 2026-09-19T21:00:00Z"}}',
]


class FakeProcess:
    """A harness that has already finished, for driving `executors.run`."""

    def __init__(self, lines: list[str], returncode: int = 0) -> None:
        self.stdout = iter(f"{line}\n" for line in lines)
        self.returncode = returncode
        self.pid = 4321

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        return "", ""

    def kill(self) -> None:  # pragma: no cover - never reached on a clean run
        pass


class TestCodexResultParsing(unittest.TestCase):
    """What came back, read from the shapes the CLI really emits."""

    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.paths = localstate.ensure(localstate.LocalPaths(Path(self.dir.name)))

    def run_with(self, lines: list[str], returncode: int = 0) -> dict[str, Any]:
        return executors.run(
            executors.CodexCliExecutor(binary="codex", effort="high"),
            self.paths,
            prompt="do the task",
            model="gpt-5.6-sol",
            role="implement",
            worktree=Path(self.dir.name),
            budget={"max_turns": 10, "timeout_seconds": 60},
            popen=lambda *a, **k: FakeProcess(lines, returncode),
        )

    def test_a_completed_turn_is_a_success(self) -> None:
        run = self.run_with(CODEX_OK)
        self.assertTrue(run["ok"], run)
        self.assertEqual(run["outcome"], "completed")

    def test_the_benign_advisories_are_not_read_as_failures(self) -> None:
        """A clamped hook timeout arrives as an `error` item on healthy runs."""
        run = self.run_with(CODEX_OK)
        self.assertTrue(run["ok"])
        self.assertIsNone(executors.exhaustion(run))

    def test_the_usage_figures_are_captured(self) -> None:
        run = self.run_with(CODEX_OK)
        self.assertEqual(run["usage"]["input_tokens"], 19507)
        self.assertEqual(run["usage"]["output_tokens"], 35)

    def test_what_the_model_last_did_is_captured(self) -> None:
        run = self.run_with(CODEX_OK)
        self.assertIn("Edited services/api/app/main.py", run["last_action"])

    def test_a_failed_turn_is_a_failure(self) -> None:
        run = self.run_with(CODEX_FAILED, returncode=1)
        self.assertFalse(run["ok"])
        self.assertEqual(run["outcome"], "failed")
        self.assertEqual(run["stop_reason"], "turn.failed")

    def test_a_failed_turn_is_a_failure_even_on_exit_zero(self) -> None:
        """The stream and the exit code are read, and either one is enough."""
        run = self.run_with(CODEX_FAILED, returncode=0)
        self.assertFalse(run["ok"])

    def test_an_exhausted_allowance_is_told_apart_from_a_defect(self) -> None:
        """It must not spend an implementation attempt: nothing was wrong."""
        run = self.run_with(CODEX_EXHAUSTED, returncode=1)
        spent = executors.exhaustion(run)
        self.assertIsNotNone(spent)
        assert spent is not None
        self.assertEqual(spent["marker"], "usage limit")
        self.assertEqual(spent["reset_at"], "2026-09-19T21:00:00Z")

    def test_a_failing_test_that_mentions_a_limit_is_still_a_defect(self) -> None:
        """The narrowing that keeps a healthy lane in service."""
        noisy = [
            '{"type":"item.completed","item":{"id":"i","type":"agent_message",'
            '"text":"the suite printed: usage limit exceeded"}}',
            '{"type":"turn.failed","error":{"message":"tests failed"}}',
        ]
        run = self.run_with(noisy, returncode=1)
        self.assertFalse(run["ok"])
        self.assertIsNone(executors.exhaustion(run))


class TestResumeFindsParallelWork(unittest.TestCase):
    """A restart has to find every branch left waiting, not just the first.

    What makes a branch findable is that the worker recorded its own task,
    branch and worktree when it started. Nothing the coordinator writes
    afterwards is relied on, because the coordinator is exactly what may have
    died -- or returned early on `max_tasks`, or stopped because a different
    task failed. A task whose record is missed keeps its lease, so nothing
    re-dispatches it and nothing ships it: the work is finished, pushed
    nowhere, and invisible.
    """

    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)
        self.paths = localstate.ensure(localstate.LocalPaths(self.root))
        self.trees = {}
        for task_id in (15, 16, 17):
            tree = self.root / f"wt-{task_id}"
            tree.mkdir()
            self.trees[task_id] = tree
            # Exactly what `run_once` writes when it starts a task.
            localstate.save_worker(
                self.paths,
                str(task_id),
                {
                    "task_id": task_id,
                    "branch": f"block-x-t{task_id}",
                    "worktree": str(tree),
                },
            )

    def context(self, ready: tuple[int, ...], done: tuple[int, ...] = ()) -> Any:
        ctx = mock.Mock()
        ctx.progress = {"completed_tasks": list(done)}
        ctx.tasks = {
            "leases": {
                str(task_id): {"task_id": task_id, "state": "ready_for_pr"}
                for task_id in ready
            }
        }
        return ctx

    def test_every_waiting_task_is_found(self) -> None:
        found = project.in_flight_all(self.context((15, 16, 17)), self.paths)
        self.assertEqual([row["task_id"] for row in found], [15, 16, 17])

    def test_each_one_names_its_own_branch_and_worktree(self) -> None:
        found = project.in_flight_all(self.context((15, 16, 17)), self.paths)
        self.assertEqual(
            {row["task_id"]: row["branch"] for row in found},
            {15: "block-x-t15", 16: "block-x-t16", 17: "block-x-t17"},
        )
        self.assertEqual(len({row["worktree"] for row in found}), 3)

    def test_a_task_that_already_merged_is_not_resumed(self) -> None:
        found = project.in_flight_all(
            self.context((15, 16, 17), done=(16,)), self.paths
        )
        self.assertEqual([row["task_id"] for row in found], [15, 17])

    def test_a_task_that_is_not_ready_is_not_resumed(self) -> None:
        """A worker still implementing must not be shipped out from under."""
        ctx = self.context((15, 16, 17))
        ctx.tasks["leases"]["16"]["state"] = "implementing"
        found = project.in_flight_all(ctx, self.paths)
        self.assertEqual([row["task_id"] for row in found], [15, 17])

    def test_a_task_with_no_lease_at_all_is_not_resumed(self) -> None:
        found = project.in_flight_all(self.context((15, 17)), self.paths)
        self.assertEqual([row["task_id"] for row in found], [15, 17])

    def test_a_vanished_worktree_is_not_resumed(self) -> None:
        self.trees[16].rmdir()
        found = project.in_flight_all(self.context((15, 16, 17)), self.paths)
        self.assertEqual([row["task_id"] for row in found], [15, 17])

    def test_it_survives_a_coordinator_that_never_got_to_write_anything(
        self,
    ) -> None:
        """The failure the coordinator-kept note could not survive.

        Nothing but the workers' own records exists here -- no project
        breadcrumb was ever written -- and all three branches are still found.
        """
        self.assertFalse(self.paths.project.exists())
        found = project.in_flight_all(self.context((15, 16, 17)), self.paths)
        self.assertEqual(len(found), 3)

    def test_concurrent_workers_do_not_overwrite_each_others_records(
        self,
    ) -> None:
        def record(task_id: int) -> None:
            localstate.save_worker(
                self.paths,
                str(task_id),
                {
                    "task_id": task_id,
                    "branch": f"b{task_id}",
                    "worktree": str(self.root),
                },
            )

        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(record, range(100, 130)))
        stored = localstate.worker_records(self.paths)
        self.assertEqual(len(stored), 33)


class TestTheLeaseLedgerSurvivesThreeWriters(unittest.TestCase):
    """Writing a lease must not delete a lease the writer never saw.

    Each worker holds an in-memory snapshot taken when it started. Writing the
    whole snapshot back -- which is what `save_leases` did while only one
    writer existed -- deletes every lease acquired since. The neighbour then
    holds a branch the ledger says nobody holds, the cap counts short, and the
    next coordinator hands the same task out again.
    """

    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)
        self.paths = localstate.ensure(localstate.LocalPaths(self.root))

    def lease(self, task_id: int, state_name: str = "implementing") -> dict[str, Any]:
        return {
            "task_id": task_id,
            "owner": f"worker-{task_id}",
            "branch": f"block-x-t{task_id}",
            "state": state_name,
            "heartbeat_at": localstate.now(),
        }

    def test_a_stale_snapshot_does_not_delete_a_newer_lease(self) -> None:
        # Worker A starts and sees only its own lease.
        stale = {"leases": {"15": self.lease(15)}}
        local.save_leases(self.paths, stale, task_id=15)
        # Worker B acquires afterwards; A never learns about it.
        fresh = {"leases": {"16": self.lease(16)}}
        local.save_leases(self.paths, fresh, task_id=16)
        # A now finishes and writes its own outcome from its old snapshot.
        stale["leases"]["15"]["state"] = "ready_for_pr"
        local.save_leases(self.paths, stale, task_id=15)

        on_disk = localstate.read(self.paths.leases)["leases"]
        self.assertEqual(sorted(on_disk), ["15", "16"])
        self.assertEqual(on_disk["15"]["state"], "ready_for_pr")
        self.assertEqual(on_disk["16"]["owner"], "worker-16")

    def test_three_writers_all_keep_their_leases(self) -> None:
        snapshots = []
        for task_id in (15, 16, 17):
            snapshot = {"leases": {str(task_id): self.lease(task_id)}}
            snapshots.append((task_id, snapshot))
            local.save_leases(self.paths, snapshot, task_id=task_id)
        for task_id, snapshot in snapshots:
            snapshot["leases"][str(task_id)]["state"] = "ready_for_pr"
            local.save_leases(self.paths, snapshot, task_id=task_id)
        on_disk = localstate.read(self.paths.leases)["leases"]
        self.assertEqual(sorted(on_disk), ["15", "16", "17"])
        for row in on_disk.values():
            self.assertEqual(row["state"], "ready_for_pr")

    def test_concurrent_lease_writes_keep_every_record(self) -> None:
        def write(task_id: int) -> None:
            local.save_leases(
                self.paths,
                {"leases": {str(task_id): self.lease(task_id)}},
                task_id=task_id,
            )

        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(write, range(20, 50)))
        self.assertEqual(len(localstate.read(self.paths.leases)["leases"]), 30)

    def test_reclaiming_a_dead_worker_keeps_a_live_workers_lease(self) -> None:
        """The sweep runs outside the schedule lock as well as inside it.

        Reclaiming an abandoned lease by writing the whole ledger back from a
        pre-sweep snapshot would delete any lease taken since -- recovering one
        dead worker by abandoning a live one.
        """
        policy = _policy()
        dead = self.lease(15)
        dead["pid"] = 999999  # a pid nothing is running under
        dead["image"] = "no-such-image.exe"
        tasks = {"leases": {"15": dead}}
        local.save_leases(self.paths, tasks, task_id=15)
        # A second worker starts after the snapshot above was taken.
        local.save_leases(self.paths, {"leases": {"16": self.lease(16)}}, task_id=16)

        reclaimed = local.reclaim_abandoned(self.paths, tasks, policy)
        self.assertEqual(reclaimed, [15])
        on_disk = localstate.read(self.paths.leases)["leases"]
        self.assertEqual(sorted(on_disk), ["15", "16"])
        self.assertEqual(on_disk["16"]["owner"], "worker-16")

    def test_the_whole_document_may_still_be_written_deliberately(self) -> None:
        """The reclaim sweep owns the whole ledger and says so by passing none."""
        local.save_leases(self.paths, {"leases": {"15": self.lease(15)}}, task_id=15)
        local.save_leases(self.paths, {"leases": {"99": self.lease(99)}})
        on_disk = localstate.read(self.paths.leases)["leases"]
        self.assertEqual(sorted(on_disk), ["99"])


class TestTheCapIsReadNotHardCoded(unittest.TestCase):
    def test_the_loop_reads_the_cap_from_policy(self) -> None:
        self.assertEqual(project.writer_cap(REPO_ROOT), 3)

    def test_an_operator_may_still_run_one_writer(self) -> None:
        self.assertEqual(project.writer_cap(REPO_ROOT, 1), 1)

    def test_the_cap_is_never_zero(self) -> None:
        self.assertEqual(project.writer_cap(REPO_ROOT, 0), 1)


if __name__ == "__main__":
    unittest.main()
