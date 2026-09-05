# ADR 0006 — Foundation authentication and RLS sequence

- Status: Accepted
- Date: 2026-09-04

## Context

Task 3 depended implicitly on identity tables introduced by Task 4. Task 5 deferred the first policies beyond the task creating protected tables, contrary to AGENTS.md.

## Decision

Task 3 depends on local infrastructure and proves verified Auth identity, cookies, callback, token forwarding, and independent JWT validation. It does not implement role-aware `/v1/me` or authorize product access. Task 4 adds the identity/team/player schema together with baseline RLS, grants, safe helpers, runtime-role database/API isolation tests, and role-aware `/v1/me`. Task 5 extends the same mandatory harness with the full matrix, mutation checks, and pooled-context regressions. Every later protected table likewise arrives with policies and isolation tests in its owning task.

The initial coach is provisioned by a documented operator-only action; signup cannot self-assign coach privileges. Unlinked authenticated users receive no team permissions. This bootstrapping path belongs to Task 4 and is tested before roster workflows.

## Consequences and validation

No role-aware stub counts as complete and no unprotected schema is handed off. Verify positive and negative runtime-role access in Task 4, then broader policy regressions in Task 5. The concrete contracts are in `docs/03-schema.md`, `docs/04-api.md`, and `docs/06-tasks.md`.
