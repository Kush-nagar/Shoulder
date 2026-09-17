"""The local dashboard.

It exists to be looked at while something else is doing the work, so the two
properties that matter are that looking changes nothing and that looking never
shows a provider key. Everything else on the page is convenience.
"""

from __future__ import annotations

import http.client
import json
import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from agentops_fixtures import REPO_ROOT

from services.agentops import dashboard, localstate


class DashboardCase(unittest.TestCase):
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
        self.paths = localstate.ensure(localstate.LocalPaths(self.root))
        localstate.save_worker(
            self.paths,
            "15",
            {
                "task_id": 15,
                "task_title": "Coach judgments",
                "role": "implement",
                "model": "claude-sonnet-5",
                "lane": "claude_subscription",
                "provider": "claude",
                "branch": "block-05-t15",
                "worktree": str(self.root.parent / "agents" / "block-05-t15"),
                "phase": "implementing",
                "started_at": localstate.now(),
                "last_action": "reading docs/04-api.md",
                "cost_usd": 0.12,
            },
        )

    def start(self) -> None:
        self.server = dashboard.build_server(self.root, self.paths, port=0)
        self.port = self.server.server_address[1]
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        # LIFO: register the close first so shutdown runs before it.
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, method: str, path: str) -> tuple[int, str]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.request(method, path)
            response = connection.getresponse()
            return response.status, response.read().decode("utf-8")
        finally:
            connection.close()


class TestItIsReadOnly(DashboardCase):
    def test_a_write_request_is_refused(self) -> None:
        """A dashboard that can act is a second way to start work."""
        self.start()
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            status, _ = self.request(method, "/state")
            self.assertEqual(status, 405, method)

    def test_refusing_names_the_only_method_allowed(self) -> None:
        self.start()
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        connection.request("POST", "/")
        response = connection.getresponse()
        self.assertEqual(response.getheader("Allow"), "GET")
        connection.close()

    def test_reading_the_page_changes_no_runtime_state(self) -> None:
        self.start()
        before_workers = self.paths.workers.read_bytes()
        before_events = (
            self.paths.events.read_bytes() if self.paths.events.exists() else b""
        )
        self.request("GET", "/")
        self.request("GET", "/state")
        after_events = (
            self.paths.events.read_bytes() if self.paths.events.exists() else b""
        )
        self.assertEqual(self.paths.workers.read_bytes(), before_workers)
        self.assertEqual(after_events, before_events)

    def test_an_unknown_path_is_a_plain_not_found(self) -> None:
        self.start()
        status, _ = self.request("GET", "/admin")
        self.assertEqual(status, 404)


class TestWhatThePageShows(DashboardCase):
    def test_the_state_endpoint_is_json(self) -> None:
        self.start()
        status, body = self.request("GET", "/state")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["workers"][0]["task_id"], 15)

    def test_a_worker_card_carries_what_an_operator_needs(self) -> None:
        self.start()
        _, body = self.request("GET", "/")
        for expected in (
            "Task 15",
            "claude-sonnet-5",
            "claude_subscription",
            "block-05-t15",
            "implementing",
            "reading docs/04-api.md",
        ):
            self.assertIn(expected, body, expected)

    def test_the_coordinator_decision_is_shown(self) -> None:
        self.start()
        _, body = self.request("GET", "/state")
        data = json.loads(body)
        self.assertIn("cloud_autonomy_enabled", data["coordinator"])
        self.assertFalse(data["local_execution"]["enabled"])
        self.assertEqual(data["coordinator"]["max_parallel_writers"], 1)

    def test_local_and_cloud_permissions_are_stated_separately(self) -> None:
        """Conflating them is what made the local runtime unusable while the
        cloud one was correctly left off."""
        self.start()
        _, body = self.request("GET", "/")
        self.assertIn("local execution not enabled", body)
        self.assertIn("cloud autonomy", body)

    def test_reported_cost_is_labelled_as_reported(self) -> None:
        """On a subscription the harness figure is notional, not billed."""
        self.start()
        _, body = self.request("GET", "/")
        self.assertIn("reported", body.lower())

    def test_the_page_survives_a_broken_repository(self) -> None:
        (self.root / "docs" / "06-tasks.md").unlink()
        self.start()
        status, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("AgentOps local runtime", body)


class TestSecretsNeverReachThePage(DashboardCase):
    def test_no_provider_key_appears_in_the_html_or_the_json(self) -> None:
        localstate.save_worker(
            self.paths, "16", {"task_id": 16, "last_action": "used sk-or-dashboard"}
        )
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-dashboard"}):
            self.start()
            _, html_body = self.request("GET", "/")
            _, json_body = self.request("GET", "/state")
        self.assertNotIn("sk-or-dashboard", html_body)
        self.assertNotIn("sk-or-dashboard", json_body)

    def test_the_page_never_prints_an_environment_secret_name_with_a_value(
        self,
    ) -> None:
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-live-value"}):
            self.start()
            _, body = self.request("GET", "/")
        self.assertNotIn("sk-or-live-value", body)


class TestRendering(unittest.TestCase):
    def test_html_is_escaped_rather_than_interpolated(self) -> None:
        data: dict[str, Any] = {
            "generated_at": "now",
            "provider": {"provider": "claude", "status": "AVAILABLE"},
            "workers": [
                {
                    "task_id": 1,
                    "title": "<script>alert(1)</script>",
                    "phase": "implementing",
                    "violations": [],
                    "cost_usd": 0,
                }
            ],
            "queue": [],
            "coordinator": {},
            "events": [],
            "usage": {},
            "failures": [],
        }
        body = dashboard.page(data)
        self.assertNotIn("<script>alert(1)</script>", body)
        self.assertIn("&lt;script&gt;", body)

    def test_an_empty_runtime_renders_without_workers(self) -> None:
        body = dashboard.page(
            {
                "generated_at": "now",
                "provider": {},
                "workers": [],
                "queue": [],
                "coordinator": {},
                "events": [],
                "usage": {},
                "failures": [],
            }
        )
        self.assertIn("No local worker has run yet", body)

    def test_the_control_center_renderer_is_reused_not_reimplemented(self) -> None:
        source = (REPO_ROOT / "services" / "agentops" / "dashboard.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("control_center.render", source)

    def test_the_default_address_is_loopback_only(self) -> None:
        self.assertEqual(dashboard.DEFAULT_HOST, "127.0.0.1")
        self.assertEqual(dashboard.DEFAULT_PORT, 4317)


if __name__ == "__main__":
    unittest.main()
