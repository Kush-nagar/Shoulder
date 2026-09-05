# ADR 0005 — Explicit atomic review publication

- Status: Accepted
- Date: 2026-08-24

Extended on 2026-09-04 by [ADR 0008](0008-judgment-revisions-and-republication.md): publication pins immutable human revisions as well as clip versions; replacement preserves the preceding visible set until an atomic swap and serializes by player/game as well as judgment. Read the extension with this original decision.

## Context

Publishing is a three-to-six-clip operation. A collection of independent judgment and worker rows does not durably identify the exact requested set, order, idempotency key, or readiness state after retries and worker restarts. That ambiguity can create duplicate jobs or partial player visibility.

## Decision

1. A publish request creates one `review_publication` and three to six ordered `review_publication_item` rows.
2. Each item records the requested judgment, clip version, and eventual ready evidence clip.
3. Clip-export jobs reference both the judgment and publication.
4. A retry reuses the publication through its idempotency key.
5. Only one transaction switches every judgment's current clip and marks the complete publication visible after all items are ready.
6. A database-backed lock keyed by judgment ID prevents overlapping nonterminal publications; an in-process mutex is insufficient across workers.

## Consequences

- Publication state survives worker crashes and retries without reconstructing intent from logs.
- A partial export can be recovered without exposing a partial set.
- The schema and worker state machine gain two small tables and explicit invariants.
- Tests must prove ordered-set persistence, idempotency, failure recovery, and atomic visibility.
