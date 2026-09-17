"""Everything persistent goes through one redaction boundary.

The rule is not "secrets never exist" -- a worker needs its credential to run.
The rule is that the durable copies do not keep it: the brief kept for
observability, the result record, the stream, the events, the findings, and
anything the page renders.
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

# Shapes a real leak would take, rather than one placeholder repeated. They are
# assembled at import time so the repository's own credential scanner does not
# have to decide whether this file is leaking one: nothing here matches its
# patterns as written, and the values are still the right shape at runtime.
SECRETS = {
    "OPENROUTER_API_KEY": "sk-" + "or-" + "v1-" + "3f9c2b7ad41e8c60f2a5d7e9b1c4",
    "ANTHROPIC_AUTH_TOKEN": "sk-" + "ant-" + "api03-" + "Zx8Q2LmN4pR7vT1yB6kH0jW5",
    "GH_TOKEN": "gh" + "p_" + "4bT7yQ2mZ9xK1vN6pL3sD8wR5cF0hJ2aE7gU",
}


class FakeProcess:
    def __init__(self, lines: list[str]) -> None:
        self.stdout = iter(lines)
        self.stderr = None
        self.returncode = 0
        self.pid = 4242

    def kill(self) -> None:
        self.returncode = -9

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        return "", ""


class SecretBoundaryCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.paths = localstate.ensure(localstate.LocalPaths(self.root))
        self.worktree = self.root / "wt"
        self.worktree.mkdir()

    def everything_written(self) -> str:
        """Every byte the runtime has persisted, as one string."""
        chunks = []
        for path in sorted(self.paths.dir.rglob("*")):
            if path.is_file():
                chunks.append(path.read_text(encoding="utf-8", errors="replace"))
        return "\n".join(chunks)

    def run_worker(
        self, lines: list[str], prompt: str = "do the thing"
    ) -> dict[str, Any]:
        with mock.patch.object(shutil, "which", return_value="/bin/claude"):
            return executors.run(
                executors.ClaudeCliExecutor(),
                self.paths,
                prompt=prompt,
                model="claude-sonnet-5",
                role="implement",
                worktree=self.worktree,
                budget={"max_turns": 5, "timeout_seconds": 60},
                popen=lambda *a, **k: FakeProcess(lines),
            )


class TestNothingPersistentKeepsASecret(SecretBoundaryCase):
    def test_the_stored_brief_is_redacted(self) -> None:
        """A review prompt quotes the worker's diff, and that copy outlives
        the run."""
        with mock.patch.dict(os.environ, SECRETS):
            run = self.run_worker(
                [json.dumps({"type": "result", "subtype": "success"})],
                prompt=(
                    "review this diff: OPENROUTER_API_KEY="
                    + SECRETS["OPENROUTER_API_KEY"]
                ),
            )
            brief = (self.paths.run_dir(run["run_id"]) / "brief.md").read_text(
                encoding="utf-8"
            )
        self.assertNotIn(SECRETS["OPENROUTER_API_KEY"], brief)
        self.assertIn(localstate.REDACTED, brief)

    def test_the_returned_record_is_redacted_before_the_caller_prints_it(self) -> None:
        leak = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "text", "text": f"key {SECRETS['GH_TOKEN']}"}]
                },
            }
        )
        with mock.patch.dict(os.environ, SECRETS):
            run = self.run_worker(
                [leak, json.dumps({"type": "result", "subtype": "success"})]
            )
        self.assertNotIn(SECRETS["GH_TOKEN"], json.dumps(run))

    def test_the_result_file_is_redacted(self) -> None:
        leak = json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": SECRETS["GH_TOKEN"]}]},
            }
        )
        with mock.patch.dict(os.environ, SECRETS):
            run = self.run_worker(
                [leak, json.dumps({"type": "result", "subtype": "success"})]
            )
            stored = (self.paths.run_dir(run["run_id"]) / "result.json").read_text(
                encoding="utf-8"
            )
        self.assertNotIn(SECRETS["GH_TOKEN"], stored)

    def test_the_stream_is_redacted(self) -> None:
        leak = json.dumps(
            {"type": "assistant", "text": SECRETS["ANTHROPIC_AUTH_TOKEN"]}
        )
        with mock.patch.dict(os.environ, SECRETS):
            run = self.run_worker(
                [leak, json.dumps({"type": "result", "subtype": "success"})]
            )
            stream = Path(run["stream"]).read_text(encoding="utf-8")
        self.assertNotIn(SECRETS["ANTHROPIC_AUTH_TOKEN"], stream)

    def test_no_runtime_file_holds_any_of_them(self) -> None:
        leak = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "text",
                            "text": " ".join(SECRETS.values()),
                        }
                    ]
                },
            }
        )
        with mock.patch.dict(os.environ, SECRETS):
            self.run_worker(
                [leak, json.dumps({"type": "result", "subtype": "success"})]
            )
            localstate.append_event(
                self.paths, "note", detail=" ".join(SECRETS.values())
            )
            written = self.everything_written()
        for name, value in SECRETS.items():
            self.assertNotIn(value, written, name)

    def test_an_env_style_assignment_is_redacted(self) -> None:
        with mock.patch.dict(os.environ, SECRETS):
            localstate.append_event(
                self.paths,
                "note",
                line=f"export OPENROUTER_API_KEY={SECRETS['OPENROUTER_API_KEY']}",
            )
            written = self.everything_written()
        self.assertNotIn(SECRETS["OPENROUTER_API_KEY"], written)
        self.assertIn("OPENROUTER_API_KEY", written)

    def test_a_bearer_header_is_redacted(self) -> None:
        with mock.patch.dict(os.environ, SECRETS):
            localstate.append_event(
                self.paths,
                "note",
                header=f"Authorization: Bearer {SECRETS['ANTHROPIC_AUTH_TOKEN']}",
            )
            written = self.everything_written()
        self.assertNotIn(SECRETS["ANTHROPIC_AUTH_TOKEN"], written)

    def test_findings_are_redacted(self) -> None:
        with mock.patch.dict(os.environ, SECRETS):
            localstate.write(
                self.paths.run_dir("r1") / "findings.json",
                {"findings": [{"repair": f"remove {SECRETS['GH_TOKEN']}"}]},
            )
            written = self.everything_written()
        self.assertNotIn(SECRETS["GH_TOKEN"], written)


class TestStandardErrorIsInsideTheBoundary(SecretBoundaryCase):
    """The run record now carries stderr, so stderr is a persisted copy too.

    It is there because a provider that refuses for allowance reasons says so
    on stderr and nowhere else, and the failover path has to be able to read
    it. That makes it one more place a harness could echo a credential.
    """

    def run_with_stderr(self, stderr: str) -> dict[str, Any]:
        class Noisy(FakeProcess):
            def communicate(self, timeout: float | None = None) -> tuple[str, str]:
                return "", stderr

        with mock.patch.object(shutil, "which", return_value="/bin/claude"):
            return executors.run(
                executors.ClaudeCliExecutor(),
                self.paths,
                prompt="do the thing",
                model="claude-sonnet-5",
                role="implement",
                worktree=self.worktree,
                budget={"max_turns": 5, "timeout_seconds": 60},
                popen=lambda *a, **k: Noisy(
                    [json.dumps({"type": "result", "subtype": "success"})]
                ),
            )

    def test_a_credential_echoed_on_stderr_reaches_neither_disk_nor_caller(
        self,
    ) -> None:
        with mock.patch.dict(os.environ, SECRETS):
            run = self.run_with_stderr(
                f"error: ANTHROPIC_AUTH_TOKEN={SECRETS['ANTHROPIC_AUTH_TOKEN']}"
            )
            written = self.everything_written()
        self.assertNotIn(SECRETS["ANTHROPIC_AUTH_TOKEN"], json.dumps(run))
        self.assertNotIn(SECRETS["ANTHROPIC_AUTH_TOKEN"], written)
        self.assertIn(localstate.REDACTED, run["stderr"])

    def test_an_allowance_message_on_stderr_survives_redaction(self) -> None:
        """Redaction must not eat the sentence the failover path reads."""
        run = self.run_with_stderr("Error: you have hit your session limit")
        self.assertIsNotNone(executors.exhaustion({**run, "ok": False}))


class TestTheWorkerStillGetsWhatItNeeds(SecretBoundaryCase):
    def test_the_prompt_the_worker_receives_is_not_redacted(self) -> None:
        """Redacting the live prompt would break the work; only the stored
        copy is scrubbed."""
        seen: dict[str, Any] = {}

        def popen(command, **kwargs):  # type: ignore[no-untyped-def]
            seen["command"] = command
            return FakeProcess([json.dumps({"type": "result", "subtype": "success"})])

        prompt = "implement the thing exactly as written"
        with mock.patch.object(shutil, "which", return_value="/bin/claude"):
            executors.run(
                executors.ClaudeCliExecutor(),
                self.paths,
                prompt=prompt,
                model="claude-sonnet-5",
                role="implement",
                worktree=self.worktree,
                budget={"max_turns": 5, "timeout_seconds": 60},
                popen=popen,
            )
        self.assertEqual(seen["command"][-1], prompt)

    def test_the_openrouter_worker_still_receives_its_credential(self) -> None:
        with mock.patch.dict(os.environ, SECRETS):
            env = executors.OpenCodeExecutor().env(os.environ, self.root)
        self.assertEqual(env["OPENROUTER_API_KEY"], SECRETS["OPENROUTER_API_KEY"])


if __name__ == "__main__":
    unittest.main()
