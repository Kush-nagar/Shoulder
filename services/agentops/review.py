"""The review verdict, decided from what the reviewer actually posted.

Review used to end by posting inline comments and succeeding either way, so
nothing downstream could tell an approved branch from a rejected one. Merge
needs a machine-readable answer, and asking a model "was that review clean?"
would spend tokens to re-derive something GitHub already records.

The verdict is therefore counted, not judged: unresolved findings the reviewer
left on the commit under review, plus any changes-requested review. It fails
closed -- an answer that cannot be obtained is treated as blocking, because
merging on a question mark is the one outcome worth avoiding.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

# The reviewer runs as an Actions identity. A finding from a human reviewer
# counts too, but a human's *approval* cannot be inferred from silence, which
# is why only explicit changes-requested reviews are read below.
GRAPHQL_THREADS = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100) {
        nodes {
          isResolved
          isOutdated
          comments(first: 1) {
            nodes { path line originalCommit { oid } body }
          }
        }
      }
      reviews(last: 50) { nodes { state } }
    }
  }
}
"""


def _gh_json(args: list[str]) -> Any | None:
    result = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout or "null")
    except json.JSONDecodeError:
        return None


def verdict(repo: str, pull_request: int) -> dict[str, Any]:
    """Whether this pull request is clear to merge on review grounds.

    An outdated thread is one whose commit the branch has moved past, which is
    what a pushed repair looks like. Counting those would make every repair
    permanently blocking no matter what it fixed, so the branch could never go
    green; a reviewer that still objects re-posts against the new commit.
    """
    owner, _, name = repo.partition("/")
    payload = _gh_json(
        [
            "api",
            "graphql",
            "-f",
            f"query={GRAPHQL_THREADS}",
            "-F",
            f"owner={owner}",
            "-F",
            f"name={name}",
            "-F",
            f"number={pull_request}",
        ]
    )
    if not payload:
        return {
            "ok": False,
            "verdict": "unknown",
            "blocking": 1,
            "reason": "could not read the review state; refusing to call it clean",
            "findings": [],
        }

    pr = payload["data"]["repository"]["pullRequest"]
    findings = []
    for thread in pr["reviewThreads"]["nodes"]:
        if thread["isResolved"] or thread["isOutdated"]:
            continue
        comments = thread["comments"]["nodes"]
        if not comments:
            continue
        first = comments[0]
        findings.append(
            {
                "path": first.get("path"),
                "line": first.get("line"),
                # Enough to act on, not the whole essay: the repairer reads the
                # thread itself, and a full body here would bloat every state
                # write and every dashboard render that quotes it.
                "summary": " ".join((first.get("body") or "").split())[:300],
            }
        )

    changes_requested = sum(
        1 for review in pr["reviews"]["nodes"] if review["state"] == "CHANGES_REQUESTED"
    )
    blocking = len(findings) + changes_requested
    return {
        "ok": True,
        "verdict": "pass" if blocking == 0 else "changes_requested",
        "blocking": blocking,
        "unresolved_threads": len(findings),
        "changes_requested_reviews": changes_requested,
        "findings": findings[:20],
    }
