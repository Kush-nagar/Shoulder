"""One page that says what the local runtime is doing.

The Control Center answers this question for the cloud, and its renderer is
reused here rather than rewritten, because two renderers would eventually
disagree and the disagreement would be the thing people debug. What this adds
is the half the cloud cannot see: which local worker is on which task, in which
worktree, at which phase, on which model, and what it last did.

Read-only on purpose. A dashboard that can act is a second way to start work,
and the runtime already has one.
"""

from __future__ import annotations

import html
import json
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from services.agentops import control_center, coordinator, local, localstate, state

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4317

PHASE_TONE = {
    "completed": "ok",
    "review": "ok",
    "implementing": "busy",
    "verification_failed": "bad",
    "implementation_failed": "bad",
    "governance_refused": "bad",
    "timeout": "bad",
    "interrupted": "warn",
}


def _elapsed(since: str | None) -> str:
    if not since:
        return "-"
    try:
        began = datetime.fromisoformat(str(since))
    except ValueError:
        return "-"
    if began.tzinfo is None:
        began = began.replace(tzinfo=UTC)
    seconds = int((datetime.now(UTC) - began).total_seconds())
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m"


def snapshot(root: Path, paths: localstate.LocalPaths) -> dict[str, Any]:
    """Everything the page shows, as data.

    Anything that needs the network or the repository is allowed to fail: a
    dashboard that goes blank because `gh` was slow is worse than one that says
    it could not read that part.
    """
    config = localstate.load_config(paths)
    data: dict[str, Any] = {
        "generated_at": localstate.now(),
        "provider": local.provider_status(config),
        "workers": [],
        "queue": [],
        "coordinator": {},
        "events": localstate.events(paths, limit=40),
        "usage": localstate.usage_totals(paths),
        "worktree_root": str(local.worktree_root(root, config)),
    }

    try:
        ctx = coordinator.load_context(root)
        ctx.tasks = local.load_leases(root, paths)
        eligible = coordinator.next_eligible(ctx)
        data["coordinator"] = {
            "autonomy_enabled": state.autonomy_enabled(ctx.policy),
            "max_parallel_writers": int(ctx.policy["autonomy"]["max_parallel_writers"]),
            "completed_tasks": len(state.completed_tasks(ctx.progress)),
            "next_task": (
                f"Task {eligible.task.id} - {eligible.task.title}" if eligible else None
            ),
            "active_leases": {
                key: lease.get("state")
                for key, lease in (ctx.tasks.get("leases") or {}).items()
            },
        }
        data["queue"] = [
            {
                "task_id": candidate.task.id,
                "title": candidate.task.title,
                "eligible": candidate.eligible,
                "missing_prerequisites": candidate.missing_prerequisites,
            }
            for candidate in coordinator.candidates(ctx)[:8]
        ]
    except Exception as failure:  # noqa: BLE001 - the page must still render
        data["coordinator"] = {"error": str(failure)[:300]}

    for key, record in sorted(localstate.worker_records(paths).items()):
        data["workers"].append(
            {
                "task_id": record.get("task_id", key),
                "title": record.get("task_title", ""),
                "role": record.get("role", ""),
                "model": record.get("model", ""),
                "lane": record.get("lane", ""),
                "provider": record.get("provider", ""),
                "branch": record.get("branch", ""),
                "worktree": record.get("worktree", ""),
                "phase": record.get("recovery_state") or record.get("phase", ""),
                "elapsed": _elapsed(record.get("started_at")),
                "last_action": record.get("last_action", ""),
                "verification": record.get("verification"),
                "violations": record.get("violations") or [],
                "cost_usd": record.get("cost_usd", 0),
            }
        )

    failures = [
        event
        for event in data["events"]
        if event.get("kind") == "task_outcome"
        and event.get("outcome") not in ("completed", None)
    ]
    data["failures"] = failures[-8:]
    # Redacted on the way out as well as on the way in. State written
    # before a key entered this environment was never scrubbed at write
    # time, and the page is the one place it would become visible.
    scrubbed: dict[str, Any] = localstate.redact(data)
    return scrubbed


def control_center_panel(root: Path) -> str:
    """The existing cloud-side view, rendered defensively."""
    try:
        return control_center.render(root)
    except Exception as failure:  # noqa: BLE001 - never fail the page for this
        return f"control center unavailable: {failure}"


STYLE = """
:root { color-scheme: light dark; --bg:#0f1115; --card:#171a21; --line:#272c36;
  --text:#e6e8ee; --muted:#9aa3b2; --ok:#4ade80; --warn:#fbbf24; --bad:#f87171;
  --busy:#60a5fa; }
* { box-sizing: border-box; }
body { margin:0; padding:24px 16px; background:var(--bg); color:var(--text);
  font:14px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.wrap { max-width:1100px; margin:0 auto; }
h1 { font-size:18px; margin:0 0 4px; }
h2 { font-size:13px; text-transform:uppercase; letter-spacing:.08em;
  color:var(--muted); margin:28px 0 10px; }
.sub { color:var(--muted); margin:0 0 8px; }
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr));
  gap:12px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:8px;
  padding:12px 14px; }
.card h3 { margin:0 0 8px; font-size:14px; }
.row { display:flex; justify-content:space-between; gap:12px; padding:2px 0; }
.row span:first-child { color:var(--muted); }
.row span:last-child { text-align:right; word-break:break-all; }
.tag { display:inline-block; padding:1px 8px; border-radius:999px; font-size:12px;
  border:1px solid var(--line); }
.ok { color:var(--ok); } .warn { color:var(--warn); } .bad { color:var(--bad); }
.busy { color:var(--busy); }
table { width:100%; border-collapse:collapse; }
td, th { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line);
  vertical-align:top; }
th { color:var(--muted); font-weight:normal; }
pre { background:var(--card); border:1px solid var(--line); border-radius:8px;
  padding:12px; overflow-x:auto; white-space:pre-wrap; word-break:break-word; }
.empty { color:var(--muted); }
@media (max-width:640px){ body{padding:16px 12px;} .row{flex-direction:column;
  gap:0;} .row span:last-child{text-align:left;} }
"""


def _rows(pairs: list[tuple[str, Any]]) -> str:
    out = []
    for label, value in pairs:
        shown = "-" if value in (None, "") else value
        out.append(
            f'<div class="row"><span>{html.escape(str(label))}</span>'
            f"<span>{html.escape(str(shown))}</span></div>"
        )
    return "".join(out)


def _queue_state(item: dict[str, Any]) -> str:
    if item.get("eligible"):
        return "eligible"
    return html.escape(f"waiting on {item.get('missing_prerequisites')}")


def _event_detail(event: dict[str, Any]) -> str:
    detail = {k: v for k, v in event.items() if k not in ("at", "kind")}
    return html.escape(json.dumps(detail)[:200])


def page(data: dict[str, Any], control_panel: str = "") -> str:
    """The whole page. Small enough to read, structured enough to scan."""
    co = data.get("coordinator") or {}
    provider = data.get("provider") or {}
    usage = data.get("usage") or {}

    workers = data.get("workers") or []
    if workers:
        cards = []
        for worker in workers:
            tone = PHASE_TONE.get(str(worker.get("phase")), "")
            phase = html.escape(str(worker.get("phase") or "-"))
            verification = worker.get("verification")
            cards.append(
                '<div class="card">'
                f"<h3>Task {html.escape(str(worker.get('task_id')))} "
                f'<span class="tag {tone}">{phase}</span></h3>'
                + _rows(
                    [
                        ("title", worker.get("title")),
                        ("role", worker.get("role")),
                        ("model", worker.get("model")),
                        ("lane", worker.get("lane")),
                        ("provider", worker.get("provider")),
                        ("branch", worker.get("branch")),
                        ("worktree", worker.get("worktree")),
                        ("elapsed", worker.get("elapsed")),
                        (
                            "verification",
                            "-"
                            if verification is None
                            else ("passed" if verification else "FAILED"),
                        ),
                        ("reported cost", f"${float(worker.get('cost_usd') or 0):.4f}"),
                        ("last action", worker.get("last_action")),
                        (
                            "violations",
                            ", ".join(worker.get("violations") or []) or "none",
                        ),
                    ]
                )
                + "</div>"
            )
        worker_html = f'<div class="grid">{"".join(cards)}</div>'
    else:
        worker_html = '<p class="empty">No local worker has run yet.</p>'

    queue = data.get("queue") or []
    queue_rows = (
        "".join(
            "<tr>"
            f"<td>{html.escape(str(item['task_id']))}</td>"
            f"<td>{html.escape(str(item['title']))}</td>"
            f"<td>{_queue_state(item)}</td>"
            "</tr>"
            for item in queue
        )
        or '<tr><td colspan="3" class="empty">nothing queued</td></tr>'
    )

    events = data.get("events") or []
    event_rows = (
        "".join(
            "<tr>"
            f"<td>{html.escape(str(event.get('at', '')))}</td>"
            f"<td>{html.escape(str(event.get('kind', '')))}</td>"
            f"<td>{_event_detail(event)}</td>"
            "</tr>"
            for event in reversed(events[-20:])
        )
        or '<tr><td colspan="3" class="empty">no events yet</td></tr>'
    )

    failures = data.get("failures") or []
    failure_rows = (
        "".join(
            "<tr>"
            f"<td>{html.escape(str(item.get('at', '')))}</td>"
            f"<td>{html.escape(str(item.get('task_id', '')))}</td>"
            f'<td class="bad">{html.escape(str(item.get("outcome", "")))}</td>'
            f"<td>{html.escape(str(item.get('lease_state', '')))}</td>"
            "</tr>"
            for item in reversed(failures)
        )
        or '<tr><td colspan="4" class="empty">none</td></tr>'
    )

    autonomy = co.get("autonomy_enabled")
    autonomy_tone = "ok" if autonomy else "warn"
    autonomy_text = "enabled" if autonomy else "disabled"
    autonomy_banner = (
        "autonomy enabled"
        if autonomy
        else "autonomy disabled - no task will be dispatched"
    )
    reported_cost = "${:.4f}".format(float(usage.get("reported_cost_usd", 0)))
    # Built before the template rather than inside it: nested quotes in an
    # f-string placeholder are Python 3.12 syntax and this runs on 3.11.
    decision_rows = _rows(
        [
            ("autonomy", autonomy_text),
            ("max parallel writers", co.get("max_parallel_writers")),
            ("completed tasks", co.get("completed_tasks")),
            ("next eligible", co.get("next_task")),
            ("error", co.get("error")),
        ]
    )
    provider_rows = _rows(
        [
            ("provider", provider.get("provider")),
            ("status", provider.get("status")),
            ("reason", provider.get("reason")),
            ("worktree root", data.get("worktree_root")),
        ]
    )
    usage_rows = _rows(
        [
            ("cost (harness reported)", reported_cost),
            ("input tokens", int(usage.get("input_tokens", 0))),
            ("output tokens", int(usage.get("output_tokens", 0))),
            ("leases", json.dumps(co.get("active_leases") or {})),
        ]
    )
    generated = html.escape(str(data.get("generated_at")))

    return f"""<!-- generated by services/agentops/dashboard.py -->
<title>AgentOps local runtime</title>
<meta http-equiv="refresh" content="5">
<style>{STYLE}</style>
<div class="wrap">
<h1>AgentOps local runtime</h1>
<p class="sub">read-only &middot; generated {generated}</p>

<h2>Coordinator</h2>
<div class="grid">
  <div class="card"><h3>Decision</h3>{decision_rows}</div>
  <div class="card"><h3>Provider</h3>{provider_rows}</div>
  <div class="card"><h3>Reported usage</h3>{usage_rows}</div>
</div>
<p class="sub"><span class="tag {autonomy_tone}">{autonomy_banner}</span></p>

<h2>Workers</h2>
{worker_html}

<h2>Queue</h2>
<table><tr><th>task</th><th>title</th><th>state</th></tr>{queue_rows}</table>

<h2>Failures and escalations</h2>
<table><tr><th>at</th><th>task</th><th>outcome</th><th>lease</th></tr>{failure_rows}</table>

<h2>Recent events</h2>
<table><tr><th>at</th><th>kind</th><th>detail</th></tr>{event_rows}</table>

<h2>Control center</h2>
<pre>{html.escape(control_panel)}</pre>
</div>
"""


class Handler(BaseHTTPRequestHandler):
    """GET only. Everything else is refused rather than quietly ignored."""

    root: Path
    paths: localstate.LocalPaths

    server_version = "AgentOpsLocal/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        return

    def _send(self, status: int, body: str, content_type: str) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's interface
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        data = snapshot(self.root, self.paths)
        if path == "/state":
            self._send(
                200, json.dumps(data, indent=2, sort_keys=True), "application/json"
            )
            return
        if path == "/":
            body = page(data, control_center_panel(self.root))
            self._send(200, str(localstate.redact(body)), "text/html")
            return
        self._send(404, "not found", "text/plain")

    def _refuse(self) -> None:
        self.send_response(405)
        self.send_header("Allow", "GET")
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_POST = _refuse
    do_PUT = _refuse
    do_DELETE = _refuse
    do_PATCH = _refuse


def build_server(
    root: Path,
    paths: localstate.LocalPaths,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"root": root, "paths": paths})
    return ThreadingHTTPServer((host, port), handler)


def serve(
    root: Path,
    paths: localstate.LocalPaths,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> None:
    server = build_server(root, paths, host=host, port=port)
    try:
        server.serve_forever()
    finally:
        server.server_close()
