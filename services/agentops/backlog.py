"""Parse the canonical Shoulder backlog.

`docs/06-tasks.md` is the authoritative task list and `docs/projects/README.md`
groups tasks into delivery blocks. Both are hand-written Markdown with a stable
shape, so this parser is deterministic: it never asks a model what a task says.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

TASK_HEADING = re.compile(r"^### Task (\d+) — (.+?)\s*$")
PHASE_HEADING = re.compile(r"^## (Phase [A-Z] — .+?)\s*$")
FIELD_LINE = re.compile(r"^\*\*(Prerequisites|Read|Test|Done):\*\*\s*(.*)$")
BLOCK_ROW = re.compile(
    r"^\|\s*(\d+)\s*\|\s*([\d,\s]+)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*$"
)
NUMBERS = re.compile(r"\d+")
# Only the leading numeric run of a Prerequisites line is a dependency list.
# Everything after it is prose, and prose contains digits -- ADR filenames,
# "2,000 human judgments" -- that are not task numbers.
LEADING_TASK_NUMBERS = re.compile(r"^(?:Tasks?\s+)?([\d]+(?:\s*[,–-]\s*\d+)*)")
RANGE = re.compile(r"(\d+)\s*[–-]\s*(\d+)")


@dataclass(frozen=True)
class Task:
    """One numbered task from `docs/06-tasks.md`."""

    id: int
    title: str
    phase: str
    prerequisites: tuple[int, ...]
    gated: bool
    read: tuple[str, ...]
    test: str
    done: str
    body: str

    @property
    def slug(self) -> str:
        return f"task-{self.id}"


@dataclass(frozen=True)
class Block:
    """One delivery block from `docs/projects/README.md`."""

    id: int
    tasks: tuple[int, ...]
    name: str
    depends_on: str

    @property
    def slug(self) -> str:
        return f"block-{self.id:02d}"


@dataclass
class Backlog:
    tasks: dict[int, Task] = field(default_factory=dict)
    blocks: dict[int, Block] = field(default_factory=dict)

    def block_for_task(self, task_id: int) -> Block | None:
        for block in self.blocks.values():
            if task_id in block.tasks:
                return block
        return None

    def task_ids(self) -> list[int]:
        return sorted(self.tasks)

    def block_ids(self) -> list[int]:
        return sorted(self.blocks)


def parse_prerequisites(value: str) -> tuple[tuple[int, ...], bool]:
    """Return the numbered prerequisites and whether a non-numeric gate applies.

    Real lines this must survive:
      "1, 2"                                  -> (1, 2)
      "17–21"                                 -> (17, 18, 19, 20, 21)
      "25, 26 (evaluation go/no-go ...)"      -> (25, 26)
      "Task 30 and at least 2,000 judgments"  -> (30,)
      "gate passed"                           -> (), gate
      "no numbered tasks; ... 0012-... .md"   -> (), no gate
    """
    gate = "gate" in value.lower()
    match = LEADING_TASK_NUMBERS.match(value.strip())
    if not match:
        return (), gate
    segment = match.group(1)
    ids: set[int] = set()
    for low, high in RANGE.findall(segment):
        start, end = int(low), int(high)
        if start <= end:
            ids.update(range(start, end + 1))
    segment = RANGE.sub("", segment)
    ids.update(int(n) for n in NUMBERS.findall(segment))
    return tuple(sorted(ids)), gate


def _strip_markdown_links(text: str) -> list[str]:
    """`docs/03-schema.md`, [ADR 0008](path.md) -> bare paths."""
    paths = re.findall(r"`([^`]+)`", text)
    paths += re.findall(r"\]\(([^)]+)\)", text)
    return [p.strip() for p in paths if p.strip()]


@dataclass
class _Accumulator:
    """A task under construction while the parser walks its section."""

    id: int
    title: str
    phase: str
    prerequisites: tuple[int, ...] = ()
    gated: bool = False
    read: tuple[str, ...] = ()
    test: str = ""
    done: str = ""
    body: list[str] = field(default_factory=list)

    def finish(self) -> Task:
        return Task(
            id=self.id,
            title=self.title,
            phase=self.phase,
            prerequisites=self.prerequisites,
            gated=self.gated,
            read=self.read,
            test=self.test,
            done=self.done,
            body="\n".join(self.body).strip(),
        )


def parse_tasks(text: str) -> dict[int, Task]:
    tasks: dict[int, Task] = {}
    phase = ""
    current: _Accumulator | None = None

    for raw in text.splitlines():
        phase_match = PHASE_HEADING.match(raw)
        if phase_match:
            phase = phase_match.group(1)
            continue

        heading = TASK_HEADING.match(raw)
        if heading:
            if current is not None:
                tasks[current.id] = current.finish()
            current = _Accumulator(
                id=int(heading.group(1)),
                title=heading.group(2).strip(),
                phase=phase,
            )
            continue

        if current is None:
            continue

        current.body.append(raw)
        field_match = FIELD_LINE.match(raw.strip())
        if not field_match:
            continue
        name, value = field_match.group(1), field_match.group(2).strip()
        if name == "Prerequisites":
            current.prerequisites, current.gated = parse_prerequisites(value)
        elif name == "Read":
            current.read = tuple(_strip_markdown_links(value))
        elif name == "Test":
            current.test = value
        elif name == "Done":
            current.done = value

    if current is not None:
        tasks[current.id] = current.finish()
    return tasks


def parse_blocks(text: str) -> dict[int, Block]:
    blocks: dict[int, Block] = {}
    for raw in text.splitlines():
        row = BLOCK_ROW.match(raw.strip())
        if not row:
            continue
        task_ids = tuple(sorted(int(n) for n in NUMBERS.findall(row.group(2))))
        if not task_ids:
            continue
        block = Block(
            id=int(row.group(1)),
            tasks=task_ids,
            name=row.group(3).strip().strip("*"),
            depends_on=row.group(4).strip(),
        )
        blocks[block.id] = block
    return blocks


def load(repo_root: Path) -> Backlog:
    tasks_doc = repo_root / "docs" / "06-tasks.md"
    blocks_doc = repo_root / "docs" / "projects" / "README.md"
    backlog = Backlog(
        tasks=parse_tasks(tasks_doc.read_text(encoding="utf-8")),
        blocks=parse_blocks(blocks_doc.read_text(encoding="utf-8")),
    )
    if not backlog.tasks:
        raise ValueError(f"no tasks parsed from {tasks_doc}")
    if not backlog.blocks:
        raise ValueError(f"no blocks parsed from {blocks_doc}")
    return backlog
