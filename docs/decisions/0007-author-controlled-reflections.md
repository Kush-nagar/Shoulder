# ADR 0007 — Author-controlled reflections

- Status: Accepted
- Date: 2026-09-04

## Context

The product called reflections append-only while the API and UI supported editing and removal.

## Decision

Keep one optional `player_reflection` per judgment. Only the linked player author can create, read, edit, or permanently delete their own reflection; their coach can read but cannot mutate its text. Creation requires currently published evidence. Existing reflections remain manageable by their author after evidence withdrawal, subject to account access and retention/erasure rules.

Updates replace text without retaining previous text in history, events, email, or job payloads. Store the published judgment version at save time to label an older reflection accurately after replacement. Deletion is idempotent, removes the active row and cached/queued copies, and prevents an old retried save from recreating it. A new deliberate creation is permitted while evidence is visible. Keep only bounded content-free replay/deletion metadata.

## Consequences and validation

Task 19 tests author-only mutation, coach read-only access, withdrawn-evidence management, delete/retry races, and no retained text. Task 22 verifies backup expiry and deletion replay. Permanent deletion is not a promise of instant erasure from backups or copies outside Shoulder; `docs/10-security-privacy.md` states the operational limits.
