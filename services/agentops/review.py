"""The review verdict, decided from what the reviewer actually posted.

Review used to end by posting inline comments and succeeding either way, so
nothing downstream could tell an approved branch from a rejected one. Merge
needs a machine-readable answer, and asking a model "was that review clean?"
would spend tokens to re-derive something GitHub already records.

The verdict is therefore counted, not judged: unresolved findings the reviewer
left on the commit under review, plus the current state of each reviewer's
latest review. It fails closed -- an answer that cannot be obtained is treated
as blocking, because merging on a question mark is the one outcome worth
avoiding.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

GRAPHQL = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      headRefOid
      reviewThreads(first: 100) {
        totalCount
        nodes {
          isResolved
          isOutdated
          comments(first: 1) {
            nodes { path line body }
          }
        }
      }
      reviews(last: 50) {
        totalCount
        nodes {
          state
          submittedAt
          author { login }
          commit { oid }
        }
      }
    }
  }
}
"""

# A review in one of these states is a remark, not a judgment, and GitHub
# records one for every inline-comment batch. Treating it as a verdict would
# make a reviewer that left a summary look like it approved, or keep a
# dismissed objection alive forever.
ADVISORY_STATES = ("COMMENTED", "PENDING", "DISMISSED")


def _gh_json(args: list[str]) -> Any | None:
    result = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout or "null")
    except json.JSONDecodeError:
        return None


def latest_review_states(reviews: list[dict[str, Any]]) -> dict[str, str]:
    """Each reviewer's current position, not their history.

    GitHub keeps every review a person submits. Counting all of them means a
    reviewer that requested changes and then approved the repaired branch still
    reads as blocking forever: the branch can never go green, the repair
    ceiling is spent achieving nothing, and the task ends up permanently
    blocked. Only the most recent substantive review per author counts.
    """
    latest: dict[str, tuple[str, str]] = {}
    for review in reviews:
        state = str(review.get("state") or "")
        if state in ADVISORY_STATES:
            continue
        author = str((review.get("author") or {}).get("login") or "")
        at = str(review.get("submittedAt") or "")
        if author not in latest or at >= latest[author][0]:
            latest[author] = (at, state)
    return {author: state for author, (_, state) in latest.items()}


THREAD_WINDOW = 100
REVIEW_WINDOW = 50


def _is_reviewer(review: dict[str, Any], reviewer_login: str | None) -> bool:
    """Whether this review came from the reviewer that was asked.

    An exact match against the two spellings GitHub actually uses for an app --
    `name` through GraphQL and `name[bot]` through REST -- and nothing else.

    It was a prefix test, which is a hole: on a public pull request an account
    called `chatgpt-codex-connector-evil` could leave a passing `COMMENTED`
    review, satisfy the wait before the real reviewer answered, and let the
    required verdict go green with no independent review at all.
    """
    if not reviewer_login:
        return True
    author = str((review.get("author") or {}).get("login") or "").lower()
    expected = reviewer_login.lower().removesuffix("[bot]")
    return author in (expected, f"{expected}[bot]")


def verdict(
    repo: str,
    pull_request: int,
    *,
    require_submitted_review: bool = False,
    reviewer_login: str | None = None,
) -> dict[str, Any]:
    """Whether this pull request is clear to merge on review grounds.

    An outdated thread is one whose commit the branch has moved past, which is
    what a pushed repair looks like. Counting those would make every repair
    permanently blocking no matter what it fixed, so the branch could never go
    green; a reviewer that still objects re-posts against the new commit.

    `require_submitted_review` is for a reviewer reached by mentioning a bot on
    the pull request. That job finishes the moment the mention is posted, while
    the review itself lands minutes later, so "not reviewed yet" and "reviewed
    and clean" look identical from here -- and the first one would merge
    unreviewed. With this set, a review actually submitted against the current
    head commit is required before the verdict may pass.
    """
    owner, _, name = repo.partition("/")
    payload = _gh_json(
        [
            "api",
            "graphql",
            "-f",
            f"query={GRAPHQL}",
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

    # Both connections are windowed, and a window is a silent truncation: an
    # unresolved thread or a changes-requested review outside it would be
    # invisible and the gate would report pass. Fail closed instead. The
    # windows are far above anything a real task produces, so reaching one is
    # itself worth stopping for.
    threads_total = int(pr["reviewThreads"].get("totalCount") or 0)
    reviews_total = int(pr["reviews"].get("totalCount") or 0)
    if threads_total > THREAD_WINDOW or reviews_total > REVIEW_WINDOW:
        return {
            "ok": False,
            "verdict": "unknown",
            "blocking": 1,
            "reason": (
                f"{threads_total} threads and {reviews_total} reviews exceed the "
                f"{THREAD_WINDOW}/{REVIEW_WINDOW} window this can read; "
                "refusing to call it clean"
            ),
            "findings": [],
        }

    head = str(pr.get("headRefOid") or "")
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

    reviews = pr["reviews"]["nodes"]
    states = latest_review_states(reviews)
    changes_requested = sum(1 for s in states.values() if s == "CHANGES_REQUESTED")

    # Any review of the current head, advisory ones included: what this answers
    # is "has the reviewer looked at this commit", not "did it approve".
    #
    # It must be THE reviewer, though. Another integration or a person leaving
    # a passing remark first would otherwise satisfy the wait, and the pull
    # request would merge without the independent reviewer that was chosen for
    # it ever answering.
    reviewed_head = any(
        str((review.get("commit") or {}).get("oid") or "") == head
        and _is_reviewer(review, reviewer_login)
        for review in reviews
    )

    blocking = len(findings) + changes_requested
    result: dict[str, Any] = {
        "ok": True,
        "blocking": blocking,
        "unresolved_threads": len(findings),
        "changes_requested_reviews": changes_requested,
        "head": head,
        "reviewed_head": reviewed_head,
        "findings": findings[:20],
    }

    if blocking:
        result["verdict"] = "changes_requested"
    elif require_submitted_review and not reviewed_head:
        # Neither a pass nor a failure: the reviewer has not answered yet. It
        # blocks, because the alternative is merging before review arrives.
        result["verdict"] = "pending"
        result["blocking"] = 1
        result["reason"] = (
            "no review has been submitted against the current head commit yet"
        )
    else:
        result["verdict"] = "pass"
    return result
