"""What an autonomous branch is not allowed to change.

Moving the real-use gate onto the protected default branch did not, by itself,
make it human-only. Both required contexts are automated, so a branch this
system wrote could edit `ops/policy.json` to set `real_use_gate: true` and the
system would author, check and merge its own permission to begin the
machine-learning phases AGENTS.md rule 5 forbids.

The decision lives here rather than in a shell loop inside the workflow so it
can be tested directly. A guard that errors blocks every merge, and a guard
that quietly matches nothing blocks none -- both are silent, and neither shows
up until it matters.
"""

from __future__ import annotations

# Everything that decides what this system may do: where work is routed, what
# it may spend, which providers are banned, the human gates, the checks
# themselves, and who has to approve. A branch that could edit any of these
# could grant itself anything else.
GUARDED = (
    "ops/policy.json",
    ".github/workflows",
    "AGENTS.md",
    "CLAUDE.md",
    "CODEOWNERS",
    ".github/CODEOWNERS",
)


def violations(changed: list[str]) -> list[str]:
    """The guarded paths this change touches, in the order they are declared.

    A guarded entry matches the file itself or anything beneath it, so naming
    a directory covers files added to it later -- which is the case that would
    otherwise slip through, since a new workflow is a new path nobody listed.
    """
    seen = []
    # `removeprefix`, not `lstrip`. `lstrip("./")` strips any leading run of
    # those two characters, so `.github/workflows/...` arrived here as
    # `github/workflows/...` and matched nothing -- the guard would have waved
    # through every workflow change it exists to stop.
    normalised = [
        path.strip().replace("\\", "/").removeprefix("./") for path in changed
    ]
    normalised = [path for path in normalised if path]
    for guard in GUARDED:
        for path in normalised:
            if path == guard or path.startswith(f"{guard}/"):
                seen.append(guard)
                break
    return seen


REFUSAL = """## Refused: an autonomous branch changed governance

Changed: {paths}

These decide what this system is permitted to do -- routing, budgets, banned
providers, the human gates, and the checks themselves. A branch this system
wrote may not change them: both required contexts are automated, so doing so
would be the system granting itself the permission.

A human makes this change from their own branch, which is not an autonomous
branch and never reaches this check.
"""


def refusal(paths: list[str]) -> str:
    return REFUSAL.format(paths=", ".join(paths))
