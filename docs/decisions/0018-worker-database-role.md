# ADR 0018 — A separate worker database role

- Status: Accepted
- Date: 2026-09-09

## Context

Task 10 introduces a background process that claims rows from `app.processing_job`,
holds a lease, heartbeats, and writes terminal state. The repository already separates
three Postgres roles: `shoulder_migration` owns the schema, `shoulder_api` is the
`NOBYPASSRLS` runtime login that every user request runs through, and `shoulder_operator`
exists only for the bootstrap transaction ([ADR 0016](0016-operator-bootstrap-privileges.md)).

None of the three fits the worker:

- `shoulder_api` authorizes from `app.user_id`, the verified subject of an HTTP request.
  A worker has no user. Giving the API role a policy that passes when `app.user_id` is
  absent would open every user request that forgets to set it — the exact failure the
  Task 4 "missing context fails closed" tests exist to prevent.
- `shoulder_operator` is the bootstrap credential and is deliberately provisioned only
  while bootstrapping.
- `shoulder_migration` owns the tables, so using it at runtime would give a long-running
  process DDL rights and the owner-maintenance policy.

`docs/10-security-privacy.md` also states the worker's boundary directly: "Read/write only
media and job objects needed for a claimed task", explicitly not "broad database
administration".

## Decision

Add a fourth role, `shoulder_worker`, in migration `0005`.

1. `NOBYPASSRLS`, `NOINHERIT`, owns no object, and has no `CREATE` in any schema.
2. `USAGE` on `app` only; no `private` execute grant, because the worker authorizes
   nothing on behalf of a user.
3. Table privileges limited to what a claim loop needs:
   `SELECT, UPDATE` on `app.processing_job` (no `INSERT`: enqueue is the API's job, and
   no `DELETE`: terminal jobs are retained for the coach-facing failure surface), and
   `SELECT` plus a column-scoped `UPDATE` on `app.video` for the status and metadata
   columns a completed task writes.
4. Its own RLS policies, distinct from the API role's: the worker sees every job row
   because it has no team context, and the row it may act on is bounded by the claim
   query and its lease, not by a membership predicate.
5. RLS stays enabled and forced on both tables, so the policy set is the audit surface;
   the worker never bypasses it.

## Consequences

- The runtime user path and the background path fail independently. A policy mistake in
  one does not widen the other, and the isolation matrix can assert both.
- `app.user_id` keeps exactly one meaning: a verified HTTP subject. Nothing has to pass
  when it is absent.
- Deployment gains one more credential to provision and rotate, recorded in the
  credentials table of `docs/10-security-privacy.md`.
- The worker's write surface widens by explicit grant as later tasks give it real work
  (Task 11 playback metadata, Task 17 clip export, Task 22 deletion). Each widening is a
  reviewable migration, not an inherited privilege.

## Alternatives rejected

- **Reuse `shoulder_api` with a null-user policy branch.** Rejected: it makes "no
  identity" an authorized state on the login every browser request uses.
- **A `SECURITY DEFINER` claim function called by `shoulder_api`.** Rejected: it hides the
  worker's whole privilege set inside one function body and still leaves the long-running
  process holding the user-request credential.
- **Connect the worker as the table owner.** Rejected: DDL and owner-maintenance rights in
  a long-lived process, contradicting the least-privilege posture in
  `docs/10-security-privacy.md`.
