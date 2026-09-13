"""Deterministic task classification.

Classification decides how much model capability a task earns, so it must be
reproducible and auditable. Every signal here is a keyword or a count taken
from the canonical task text; no model is asked to classify anything.

Complexity and risk are separate axes. A five-line RLS change is small and
still critical, so risk raises the final class as a hard override rather than
being averaged into a score.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Literal

from .backlog import Task

Category = Literal["frontend", "backend", "mixed"]
Complexity = Literal["TRIVIAL", "ROUTINE", "COMPLEX", "CRITICAL", "EXTREME"]

# Signals are matched against the lower-cased task body plus its title.
SECURITY_SIGNALS = (
    "rls",
    "row-level",
    "policy",
    "policies",
    "grant",
    "isolation",
    "authoriz",
    "authentic",
    "signed url",
    "signing",
    "session",
    "token",
    "privacy",
    "cross-player",
    "spoof",
)
# Data that stops existing. A short signed-URL lifetime is not destructive, so
# "expire"/"expiry" are deliberately absent: they appear in every storage task.
DESTRUCTIVE_SIGNALS = (
    "deletion",
    "delete",
    "retention",
    "withdraw",
    "purge",
    "cleanup",
    "data loss",
)
MIGRATION_SIGNALS = ("schema", "migration", "alembic", "table", "foreign key")
FRONTEND_SIGNALS = (
    "ui",
    "screen",
    "viewport",
    "mobile",
    "responsive",
    "component",
    "player screen",
    "keyboard",
    "scrubber",
    "timeline",
    "accessib",
    "copy",
    "/coach/",
    "/player/",
)
BACKEND_SIGNALS = (
    "api",
    "fastapi",
    "endpoint",
    "worker",
    "queue",
    "storage",
    "bucket",
    "database",
    "postgres",
    "job",
    "ffmpeg",
    "transcode",
)
VISUAL_SIGNALS = ("viewport", "responsive", "mobile", "design system", "screenshot")
BROWSER_SIGNALS = ("playwright", "browser", "keyboard", "reload", "offline")
FRONTEND_DOCS = ("docs/05-ui.md", "docs/09-frontend-design-system.md")
BACKEND_DOCS = ("docs/03-schema.md", "docs/04-api.md", "docs/02-architecture.md")
# External libraries whose current documentation materially affects correctness.
CONTEXT7_SIGNALS = (
    "next.js",
    "supabase",
    "fastapi",
    "tailwind",
    "alembic",
    "playwright",
    "resend",
    "vercel",
    "fly.io",
    "ffmpeg",
    "r2",
    "boto3",
)


@dataclass(frozen=True)
class Classification:
    task_id: int
    category: Category
    complexity: Complexity
    security_risk: bool
    destructive_risk: bool
    migration_risk: bool
    visual_required: bool
    browser_required: bool
    context7_expected: bool
    prerequisite_count: int
    test_clause_count: int
    read_doc_count: int
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _hits(text: str, signals: tuple[str, ...]) -> list[str]:
    return [s for s in signals if s in text]


def _count_clauses(test: str) -> int:
    """`Test:` lines list checks separated by semicolons -- a size proxy."""
    if not test.strip():
        return 0
    return len([c for c in re.split(r"[;.]", test) if c.strip()])


def classify(task: Task, *, prior_failures: int = 0) -> Classification:
    text = f"{task.title}\n{task.body}".lower()
    reads = tuple(r.lower() for r in task.read)

    security = bool(_hits(text, SECURITY_SIGNALS))
    destructive = bool(_hits(text, DESTRUCTIVE_SIGNALS))
    migration = bool(_hits(text, MIGRATION_SIGNALS))
    visual = bool(_hits(text, VISUAL_SIGNALS))
    browser = bool(_hits(text, BROWSER_SIGNALS))

    frontend_score = len(_hits(text, FRONTEND_SIGNALS)) + sum(
        2 for d in FRONTEND_DOCS if d in reads
    )
    backend_score = len(_hits(text, BACKEND_SIGNALS)) + sum(
        2 for d in BACKEND_DOCS if d in reads
    )
    if frontend_score and backend_score and abs(frontend_score - backend_score) <= 2:
        category: Category = "mixed"
    elif frontend_score > backend_score:
        category = "frontend"
    else:
        # No signal either way falls to backend, the safer default: the frontend
        # lane carries a hard writer restriction that must not be entered by
        # accident.
        category = "backend"

    test_clauses = _count_clauses(task.test)
    prereqs = len(task.prerequisites)
    reads_count = len(task.read)

    # Scope score: how much surface the task touches, independent of risk.
    scope = 0
    scope += min(test_clauses // 3, 4)
    scope += min(prereqs, 3)
    scope += min(reads_count // 2, 3)
    scope += min(len(task.body) // 900, 3)

    if scope <= 2:
        complexity: Complexity = "TRIVIAL"
    elif scope <= 5:
        complexity = "ROUTINE"
    elif scope <= 9:
        complexity = "COMPLEX"
    else:
        complexity = "CRITICAL"

    reasons = [f"scope={scope}", f"category={category}"]

    # Risk overrides. These raise the floor and never lower it.
    order: list[Complexity] = ["TRIVIAL", "ROUTINE", "COMPLEX", "CRITICAL", "EXTREME"]

    def raise_to(floor: Complexity, why: str) -> None:
        nonlocal complexity
        if order.index(floor) > order.index(complexity):
            complexity = floor
            reasons.append(why)

    if security:
        raise_to("CRITICAL", "security/privacy surface")
    if destructive:
        raise_to("CRITICAL", "destructive or retention behaviour")
    if migration:
        # AGENTS.md requires RLS, grants, and runtime-role isolation tests in the
        # same task that introduces a protected table, whether or not the task
        # text says so. Schema work is never routine here.
        raise_to("COMPLEX", "introduces or alters schema")
    if migration and security:
        raise_to("CRITICAL", "migration touching protected data")

    # Repeated failure is the only path to EXTREME; it is an escalation state.
    if prior_failures >= 2:
        raise_to("EXTREME", f"escalated after {prior_failures} failed attempts")

    context7 = bool(_hits(text, CONTEXT7_SIGNALS))

    return Classification(
        task_id=task.id,
        category=category,
        complexity=complexity,
        security_risk=security,
        destructive_risk=destructive,
        migration_risk=migration,
        visual_required=visual,
        browser_required=browser,
        context7_expected=context7,
        prerequisite_count=prereqs,
        test_clause_count=test_clauses,
        read_doc_count=reads_count,
        reasons=tuple(reasons),
    )
