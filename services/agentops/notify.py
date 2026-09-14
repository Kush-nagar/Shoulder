"""The activity feed.

Milestones go to one long-lived GitHub issue so the project has a durable,
notifiable log that outlives any session. Shell commands, tool calls, file
reads, and raw logs deliberately do not: a feed nobody reads is not a feed.
"""

from __future__ import annotations

import re
import subprocess
from typing import Any

MARKERS = {
    "start": "▶",
    "checkpoint": "◐",
    "verify": "🧪",
    "pr": "🔀",
    "review_start": "🔎",
    "review_pass": "✅",
    "review_fail": "❌",
    "ci_pass": "✅",
    "ci_fail": "⚠",
    "provider": "↪",
    "merge": "✅",
    "next": "▶",
    "blocked": "⛔",
    "budget": "💰",
    "complete": "🏁",
}

# Shapes that are a credential wherever they appear. Matching one of these in
# a committed file means a real secret leaked.
CREDENTIAL_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"\bsk-or-v1-[A-Za-z0-9]{8,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bey[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)
# Deliberately over-eager, and only applied to text bound for the activity
# feed. It catches `token=...` and `secret: ...`, which is a real leak, but it
# also flags a configuration key merely *named* secret. Over-redacting one feed
# comment costs nothing; missing a credential does not.
ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password)\b\s*[:=]\s*\S+"
)
SECRET_PATTERNS = (*CREDENTIAL_PATTERNS, ASSIGNMENT_PATTERN)
REDACTED = "[redacted]"


def redact(text: str) -> str:
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def format_event(
    kind: str, headline: str, details: dict[str, Any] | None = None
) -> str:
    marker = MARKERS.get(kind, "•")
    lines = [f"{marker} **{redact(headline)}**"]
    for key, value in (details or {}).items():
        if value in (None, "", [], {}):
            continue
        lines.append(f"- {key}: {redact(str(value))}")
    return "\n".join(lines)


def _gh(
    args: list[str], *, repo: str | None = None
) -> subprocess.CompletedProcess[str]:
    command = ["gh", *args]
    if repo:
        command += ["--repo", repo]
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )


def find_issue(title: str, *, repo: str | None = None) -> int | None:
    result = _gh(
        [
            "issue",
            "list",
            "--state",
            "all",
            "--search",
            title,
            "--json",
            "number,title",
        ],
        repo=repo,
    )
    if result.returncode != 0:
        return None
    import json

    for issue in json.loads(result.stdout or "[]"):
        if issue.get("title") == title:
            return int(issue["number"])
    return None


def ensure_issue(title: str, body: str, *, repo: str | None = None) -> int | None:
    existing = find_issue(title, repo=repo)
    if existing is not None:
        return existing
    result = _gh(["issue", "create", "--title", title, "--body", body], repo=repo)
    if result.returncode != 0:
        return None
    match = re.search(r"/issues/(\d+)", result.stdout)
    return int(match.group(1)) if match else find_issue(title, repo=repo)


FEED_BODY = """Durable milestone feed for the autonomous build system.

The coordinator, workers, and watchdog post here: task starts, checkpoints,
verification results, pull requests, reviews, CI state changes, provider
switches, merges, blockers, and budget warnings. Shell commands, tool calls,
file reads, and raw logs stay out by design.

Watch this issue to receive notifications through normal GitHub channels.
"""


def ensure_feed(policy: dict[str, Any], *, repo: str | None = None) -> int | None:
    """The feed issue, created if this repository does not have one yet.

    Callers used to look the issue up and give up when it was missing, which
    meant a fresh repository silently dropped every event.
    """
    return ensure_issue(policy["notifications"]["issue_title"], FEED_BODY, repo=repo)


def post(
    issue: int,
    kind: str,
    headline: str,
    details: dict[str, Any] | None = None,
    *,
    repo: str | None = None,
) -> bool:
    body = format_event(kind, headline, details)
    result = _gh(["issue", "comment", str(issue), "--body", body], repo=repo)
    return result.returncode == 0
