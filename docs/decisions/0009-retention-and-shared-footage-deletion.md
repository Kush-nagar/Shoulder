# ADR 0009 — Retention and shared-footage deletion

- Status: Accepted engineering policy; operational owner confirmation required before real data
- Date: 2026-09-04

## Context

Processing success previously started a 90-day clock that never started for failures. Season expiry had no date field. Removing only a player's linked clips cannot remove their image from shared footage or another player's clips.

## Decision

- An incomplete upload expires seven days after initiation; resume does not extend it. Invalid/rejected media is made inaccessible immediately and deleted within 24 hours.
- Completed media that never becomes ready is deleted by the earlier of seven days after first terminal processing failure or fourteen days after upload completion. Retries do not extend these deadlines. A successful retry before expiry moves to successful-source retention. Source expiry is always capped at ninety days after upload completion, or earlier season/erasure expiry.
- Successful raw sources expire at that ninety-day cap, not ninety days after processing. Derivatives and season-scoped product content expire at `season_end_at + 365 days`. `team.season_end_at` is required and owner-confirmed; it cannot be extended once team product data exists. A new season is explicitly outside this initial one-season workspace. Expiry applies to drafts, revisions, unpublished exports, and reflections as well as current clips.
- A verified player-erasure request immediately blocks that player's access and all potentially affected media signing/exports. The conservative MVP scope is all stored videos for that player's team, all their derivatives (including clips published to other players), and all product rows dependent on those videos. No face recognition or selective anonymization is claimed. Unrelated other-player goals/accounts may remain only after an operator checks them for the requesting player's personal data. The operator reviews the explicit impact list before executing the documented deletion challenge; this does not substitute for evaluating the request under applicable obligations.
- Worker races must not recreate deleted objects. Retain a restricted, content-free deletion manifest until jobs, objects, caches, and restore replay are reconciled. Delete identifiers when their operational retention ends. Application access stays blocked on partial failure.
- Backups containing personal data must have an owner-verified maximum expiry of thirty days; restore replays deletions before enabling access. If providers cannot meet that policy, real-data onboarding is blocked pending a reviewed ADR. Downloaded copies outside Shoulder and statutory obligations cannot be certified by this engineering policy.

## Consequences and validation

Shared-footage erasure deliberately removes other players' affected evidence; it is not a selective-delete feature. Before real data, the owner must confirm the notice, season date, collateral-deletion policy, responsible operator, and actual provider backup behavior. Task 22 proves deadlines, a two-player shared-video deletion, concurrent worker fencing, content-free manifests, and restore suppression. `docs/10-security-privacy.md` contains the full retention table and procedure.
