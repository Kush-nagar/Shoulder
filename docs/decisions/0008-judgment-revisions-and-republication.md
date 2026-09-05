# ADR 0008 — Judgment revisions and republication

- Status: Accepted; extends ADR 0005
- Date: 2026-09-04

## Context

Mutable judgment fields and clip versions alone do not preserve human edit history or prevent a new sentence from being paired with an old player clip.

## Decision

1. `judgment` holds stable identity, its latest positive integer version, and current publication/revision/clip pointers. Editable text, verdict, and clip bounds live in immutable `judgment_revision` snapshots. Creation writes version 1; each accepted content edit increments by exactly one and writes a full snapshot in the same transaction. A no-op or replay does not create another revision. Only the original coach author may edit, while still authorized for the team.
2. `If-Match` is required for edits. A stale version returns 409 without writing. Concurrent edits serialize at the judgment row. Ordinary roles cannot update/delete revision rows; verified retention/erasure is the explicit deletion exception.
3. Each publication item pins a judgment revision and a clip version. Workers use this snapshot, never the latest mutable choice. Changed revisions, including comment-only edits, receive new isolated clip versions. Unchanged items may reuse a ready clip for that exact revision.
4. A replacement names the current publication it replaces and a complete ordered set of 3–6 judgments for the same player/game and active goal. Serialize publication requests per player/game as well as overlapping judgments. Exactly one published set and one exporting request per player/game are allowed. Validate expected versions on request; block edits to reserved judgments while exporting with 409. Retry preserves the pinned request; changing it requires cancelling the pending publication and submitting a new idempotency key.
5. Players read only current published snapshots. Old text, verdicts, and clips remain visible throughout editing/export/failure. Successful replacement atomically marks the old publication superseded, switches all current pointers, and clears omitted items. Failed or cancelled replacements cannot change the old set. First publication remains wholly invisible until ready.
6. Withdrawal blocks new reads/signing immediately and cancels any pending replacement for that player/game so it cannot resurrect evidence. It can leave fewer than three clips; all new publications still require 3–6. Already issued URLs have bounded residual access: player URLs last at most five minutes. Old/withdrawn objects are deleted within 24 hours. Clients refresh the whole evidence set after a swap, never mixing revision text and media.

## Consequences and validation

Retry after failure reacquires reservations and rejects with 409 if the coach has since edited a pinned judgment or the predecessor/withdrawal state changed. A retry cannot make an obsolete snapshot current or resurrect withdrawn evidence; a new deliberate publish request is required.

Draft rejection does not silently withdraw an old published revision. The coach UI must say this explicitly and provide withdrawal. Reflections remain player-authored, with their saved publication version distinguished after replacement. Task 15 owns revisions and their RLS; Task 17 owns publication pointers, exports, locking, and swap/withdrawal tests; Tasks 18–19 own player snapshot consistency and reflections. History is private, except the exact currently published revision, and is erased under the same retention policy as the judgment.
