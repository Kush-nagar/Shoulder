# ADR 0002 — Shared agent instructions

- Status: Accepted
- Date: 2026-08-24

## Context

Codex and Claude Code use different repository instruction entry points. Duplicating a long instruction file for each tool creates drift, while assuming Claude Code automatically reads `AGENTS.md` leaves it without the product and privacy contract.

## Decision

- `AGENTS.md` is the canonical repository instruction file.
- `CLAUDE.md` begins with `@AGENTS.md` and contains only Claude-specific operating notes.
- Durable task state lives in `STATUS.md` rather than a chat transcript.
- Directory-specific `AGENTS.md` files may be added only when a subtree needs genuinely different commands or constraints.

## Consequences

- Both tools receive one source of product truth.
- Claude-specific instructions stay short enough to remain salient.
- A change to the shared contract happens once and is reviewable.
- The setup depends on keeping the import intact and running both tools from the repository.
