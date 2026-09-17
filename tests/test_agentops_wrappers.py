"""The PowerShell wrappers, exercised as a shell actually runs them.

These are the documented entry points, and they were broken in a way no Python
test could see: `& $uv @(...) + $CliArgs` puts the `+` in argument mode, where
it is not an operator. uv received a literal "+" and every wrapper command was
malformed. So the wrapper is run here for real, against a stub that records the
argument vector it was handed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from agentops_fixtures import REPO_ROOT

STUB = """param()
$json = $args | ConvertTo-Json -Compress
$json | Out-File -FilePath $env:AGENTOPS_ARGV_OUT -Encoding utf8
exit 0
"""


def powershell() -> str | None:
    return shutil.which("pwsh") or shutil.which("powershell")


@unittest.skipUnless(powershell(), "no PowerShell on this machine")
class WrapperCase(unittest.TestCase):
    script = "agentops-local.ps1"

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.stub = Path(self.tmp.name) / "uv-stub.ps1"
        self.stub.write_text(STUB, encoding="utf-8")
        self.argv_out = Path(self.tmp.name) / "argv.json"

    def invoke(self, *args: str) -> list[str]:
        """Run the wrapper and return the argv the stub uv received."""
        env = dict(os.environ)
        env["SHOULDER_UV_PATH"] = str(self.stub)
        env["AGENTOPS_ARGV_OUT"] = str(self.argv_out)
        shell = powershell()
        assert shell is not None
        result = subprocess.run(
            [
                shell,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(REPO_ROOT / "scripts" / self.script),
                *args,
            ],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"wrapper failed: {result.stdout}\n{result.stderr}",
        )
        self.assertTrue(
            self.argv_out.exists(), f"stub never ran: {result.stdout}{result.stderr}"
        )
        recorded = json.loads(self.argv_out.read_text(encoding="utf-8-sig"))
        return [str(item) for item in recorded]


class TestTheLocalWrapper(WrapperCase):
    def assert_clean(self, argv: list[str]) -> None:
        self.assertNotIn("+", argv, f"literal + reached the CLI: {argv}")
        self.assertEqual(
            argv[:5],
            ["run", "--locked", "python", "-m", "services.agentops.cli"],
            argv,
        )

    def test_status_forwards_a_clean_argument_vector(self) -> None:
        argv = self.invoke("status")
        self.assert_clean(argv)
        self.assertEqual(argv[5:], ["local-status"])

    def test_start_authorises_local_execution(self) -> None:
        argv = self.invoke("start", "-Once")
        self.assert_clean(argv)
        self.assertIn("run", argv[5:])
        self.assertIn("--enable", argv)
        self.assertIn("--once", argv)

    def test_start_forwards_the_verification_kind(self) -> None:
        argv = self.invoke("start", "-Verification", "gated")
        self.assertEqual(argv[argv.index("--verification") + 1], "gated")
        self.assertNotIn("+", argv)

    def test_stop(self) -> None:
        self.assertEqual(self.invoke("stop")[5:], ["stop"])

    def test_resume(self) -> None:
        self.assertEqual(self.invoke("resume")[5:], ["resume"])

    def test_doctor(self) -> None:
        self.assertEqual(self.invoke("doctor")[5:], ["doctor"])

    def test_models(self) -> None:
        self.assertEqual(self.invoke("models")[5:], ["models"])

    def test_dry_run(self) -> None:
        self.assertEqual(self.invoke("dry-run")[5:], ["dry-run"])

    def test_evaluate_forwards_every_model(self) -> None:
        argv = self.invoke(
            "evaluate", "-Models", "deepseek/deepseek-v3,qwen/qwen3-coder"
        )
        self.assert_clean(argv)
        self.assertEqual(argv[5], "evaluate")
        self.assertIn("deepseek/deepseek-v3", argv)
        self.assertIn("qwen/qwen3-coder", argv)

    def test_dashboard_forwards_the_port(self) -> None:
        argv = self.invoke("dashboard", "-Port", "4318")
        self.assert_clean(argv)
        self.assertEqual(argv[5], "serve")
        self.assertEqual(argv[argv.index("--port") + 1], "4318")


class TestTheProviderWrapper(WrapperCase):
    script = "agentops-provider.ps1"

    def test_claude(self) -> None:
        argv = self.invoke("claude")
        self.assertNotIn("+", argv)
        self.assertEqual(argv[-2:], ["provider", "claude"])

    def test_openrouter(self) -> None:
        self.assertEqual(self.invoke("openrouter")[-2:], ["provider", "openrouter"])

    def test_status(self) -> None:
        self.assertEqual(self.invoke("status")[-2:], ["provider", "status"])


class TestTheWrappersHoldNoLogic(unittest.TestCase):
    def test_no_wrapper_builds_an_argument_list_with_a_bare_plus(self) -> None:
        """The defect this file exists for, asserted statically as well: the
        concatenation must happen before the call, not in argument mode."""
        for name in ("agentops-local.ps1", "agentops-provider.ps1"):
            source = (REPO_ROOT / "scripts" / name).read_text(encoding="utf-8")
            for line in source.splitlines():
                stripped = line.strip()
                if stripped.startswith("& $uv"):
                    self.assertNotIn(" + ", stripped, f"{name}: {stripped}")


if __name__ == "__main__":
    unittest.main()
