"""Runtime state lives on its own branch, not on the protected default branch.

Leases, provider health, spend and the progress ledger change many times per
task. They were pushed straight to the default branch, which meant autonomy
could only run if that branch let a bot push to it without passing checks --
either unprotected, or protected with a bypass. On a personal repository there
is no GitHub Actions bypass actor to grant, so that design simply could not
run.

So the mutable state moved to `agentops-state`: an orphan branch holding
`ops/state/` and nothing else. Product code stays on the default branch behind
required checks, and nothing in normal operation ever pushes there.

The commit is built with a throwaway index rather than by switching branches.
Two reasons. Checking out an orphan branch would empty the worktree of the very
code that is running, and the old branch-switching dance was itself the source
of several bugs -- a worker once risked pushing task-branch content onto main.
Building the tree explicitly means the pushed commit *cannot* contain anything
outside `ops/state/`; that is a property of how it is constructed, not a rule
someone has to remember.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

BRANCH = "agentops-state"
TRACKED = "ops/state"

# Carried here rather than left to `git config` in each workflow. A runner with
# no identity configured fails `commit-tree` outright, and that failure would
# look like a lost race rather than a missing setting.
IDENTITY = {
    "GIT_AUTHOR_NAME": "shoulder-agentops[bot]",
    "GIT_AUTHOR_EMAIL": "shoulder-agentops@users.noreply.github.com",
    "GIT_COMMITTER_NAME": "shoulder-agentops[bot]",
    "GIT_COMMITTER_EMAIL": "shoulder-agentops@users.noreply.github.com",
}


class StateBranchError(RuntimeError):
    """The state branch could not be read or written."""


def _git(
    root: Path, *args: str, env: dict[str, str] | None = None, check: bool = True
) -> str:
    merged = {**os.environ, **IDENTITY, **(env or {})}
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        env=merged,
    )
    if check and result.returncode != 0:
        raise StateBranchError(
            f"git {' '.join(args)} failed: {result.stderr.strip()[:400]}"
        )
    return result.stdout.strip()


def remote_ref(root: Path) -> str | None:
    """The state branch's current commit on the remote, or None if it has none."""
    listing = _git(root, "ls-remote", "origin", f"refs/heads/{BRANCH}", check=False)
    if not listing:
        return None
    return listing.split()[0]


def _base_marker(root: Path) -> Path:
    """Where the commit this worktree pulled is remembered.

    Inside `.git`, so it is never a candidate for the tree a push builds and
    can never be mistaken for repository content. `pull` and `push` are
    separate process invocations, so this has to outlive both.

    Absolute, deliberately. `--git-dir` answers relative to the repository, and
    resolving that against the *process* working directory pointed every
    repository at one shared marker: a second checkout would then overwrite the
    first's idea of what it had read, the race check would compare a commit to
    itself, and a push would quietly delete a file another writer had just
    added. Which is precisely the failure this marker exists to prevent.
    """
    return Path(_git(root, "rev-parse", "--absolute-git-dir")) / "agentops-state-base"


def pull(root: Path) -> dict[str, object]:
    """Bring `ops/state` in the worktree up to the state branch.

    When the branch does not exist yet the files already committed on the
    default branch are the seed, and are left exactly as they are. That is what
    makes the first run on a fresh repository work, and what migrates an
    existing repository without a separate step: the first `push` turns the
    seed into the branch.
    """
    head = remote_ref(root)
    marker = _base_marker(root)
    if head is None:
        marker.write_text("", encoding="utf-8")
        return {"branch": BRANCH, "existed": False, "head": None, "source": "seed"}

    _git(root, "fetch", "origin", f"+refs/heads/{BRANCH}:refs/remotes/origin/{BRANCH}")
    # Updates the worktree and index for these paths only, without moving HEAD,
    # so the product code this process is running stays exactly where it is.
    _git(root, "checkout", f"origin/{BRANCH}", "--", TRACKED)
    marker.write_text(head, encoding="utf-8")
    return {"branch": BRANCH, "existed": True, "head": head, "source": "branch"}


def changed_files(root: Path) -> list[str]:
    """State files this run has altered, so a lost race can re-apply them.

    Read from `git status` rather than a diff against the branch. A diff sees
    only tracked modifications: a state file this run *created* would not
    appear, and re-applying would then silently drop it. A diff also needs the
    remote-tracking ref to exist locally, which it does not on the first push
    of a run, and the error was swallowed into "nothing changed".
    """
    if remote_ref(root) is None:
        # No branch yet, so everything present is this run's contribution.
        return sorted(
            str(p.relative_to(root)).replace("\\", "/")
            for p in (root / TRACKED).glob("*.json")
        )
    listed = _git(root, "status", "--porcelain", "--untracked-files=all", "--", TRACKED)
    names = []
    for line in listed.splitlines():
        if not line.strip():
            continue
        # "XY path", and a rename carries "old -> new"; the new name is ours.
        # Sliced at two, not three: the separator is one space for a tracked
        # change but the field is fixed-width, and taking three swallowed the
        # first character of the path.
        path = line[2:].strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        names.append(path)
    return sorted(set(names))


def push(root: Path, message: str, *, retries: int = 4) -> dict[str, object]:
    """Commit `ops/state` onto the state branch and push it.

    On a losing race this re-reads the branch, re-applies only the files this
    run actually changed, and tries again. Files it did not touch keep the
    other writer's version, which is what a successful rebase used to do.

    Two writers changing the *same* file is the case this cannot merge, and
    there the last writer wins. That is why the callers whose mutation is cheap
    to repeat -- the worker and the pull-request reaction, which each make one
    small change -- re-run the mutation themselves against freshly pulled state
    instead of relying on this. The coordinator cannot: acquiring a lease
    increments an attempt counter, so re-running it would spend the task's
    attempt budget on a push race.
    """
    mine = {
        name: (root / name).read_bytes()
        for name in changed_files(root)
        if (root / name).exists()
    }
    attempt = 0
    while True:
        result = _push_once(root, message)
        if result["pushed"] or attempt >= retries:
            result["retries_used"] = attempt
            result["reapplied"] = sorted(mine) if attempt else []
            return result
        attempt += 1
        # Someone landed first. Take their branch, put this run's files back on
        # top of it, and try again.
        pull(root)
        for name, blob in mine.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(blob)


def _push_once(root: Path, message: str) -> dict[str, object]:
    """Build and push one commit, refusing if the branch moved since `pull`.

    The parent is the commit this worktree actually read, not whatever the
    remote holds now. Taking the current head instead would make every push a
    fast-forward and therefore always succeed -- and because the tree is built
    from this worktree's `ops/state` alone, a file another writer had just
    added would be silently deleted by the very push that appeared to work.
    """
    remote = remote_ref(root)
    marker = _base_marker(root)
    base = marker.read_text(encoding="utf-8").strip() if marker.exists() else None
    base = base or None

    if remote != base:
        return {
            "pushed": False,
            "changed": True,
            "commit": None,
            "parent": base,
            "detail": f"the branch moved from {base} to {remote}",
        }

    parent = remote
    if parent is not None:
        _git(
            root,
            "fetch",
            "origin",
            f"+refs/heads/{BRANCH}:refs/remotes/origin/{BRANCH}",
        )

    with tempfile.TemporaryDirectory() as scratch:
        index = str(Path(scratch) / "index")
        env = {"GIT_INDEX_FILE": index}
        # An empty index, then only the state directory. Nothing else in the
        # worktree can reach the tree this builds.
        _git(root, "read-tree", "--empty", env=env)
        _git(root, "add", "--all", "--", TRACKED, env=env)
        tree = _git(root, "write-tree", env=env)

    if parent is not None:
        existing = _git(root, "rev-parse", f"origin/{BRANCH}^{{tree}}", check=False)
        if existing == tree:
            return {"pushed": True, "changed": False, "commit": parent}

    args = ["commit-tree", tree, "-m", message]
    if parent is not None:
        args += ["-p", parent]
    commit = _git(root, *args)

    # Compare-and-swap, done with git's own default: this commit's parent is
    # the branch head this worktree read, so an ordinary push is a
    # fast-forward exactly when nothing has landed since, and git rejects it
    # as non-fast-forward when something has. No force of any kind -- the
    # whole point is that a losing writer must lose, and be told so, rather
    # than overwrite a lease, a spend record, or a repair count.
    before = remote_ref(root)
    _git(root, "push", "origin", f"{commit}:refs/heads/{BRANCH}", check=False)
    landed = remote_ref(root)
    ok = landed == commit
    detail = "" if ok else f"rejected; the branch is at {landed}, was {before}"
    if ok:
        marker.write_text(commit, encoding="utf-8")
    return {
        "pushed": ok,
        "changed": True,
        "commit": commit if ok else None,
        "parent": parent,
        "detail": detail,
    }


def contents(root: Path) -> list[str]:
    """Every path the state branch holds, for tests and for diagnosis."""
    if remote_ref(root) is None:
        return []
    _git(root, "fetch", "origin", f"+refs/heads/{BRANCH}:refs/remotes/origin/{BRANCH}")
    listed = _git(root, "ls-tree", "-r", "--name-only", f"origin/{BRANCH}")
    return sorted(line for line in listed.splitlines() if line)
