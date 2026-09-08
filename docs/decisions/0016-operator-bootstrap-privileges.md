# ADR 0016 — Operator bootstrap database privileges

- Status: Accepted
- Date: 2026-09-08

Task 4's specified `POST /v1/teams` operator bootstrap used the ordinary API
database role to execute a privileged helper. Direct runtime database access
could therefore create a coach without the HTTP operator-token check.

Keep the specified endpoint and its constant-time operator-token check, but
execute its single transaction through `OPERATOR_DATABASE_URL`, authenticated
as `shoulder_operator`. This role has only private-schema usage and execution
of `private.bootstrap_initial_team`; it has no product-table grants, ownership,
role memberships, administrative privileges, or RLS bypass. `shoulder_api`
cannot execute that helper or assume either privileged role. Migration
credentials are never used by the endpoint. Missing operator configuration
disables bootstrap. No dependency is added.

The operator provisions a temporary password out of band, supplies the database
URL and a random operator token of at least 32 characters only for bootstrap,
then clears both settings and removes the database password. The token format
and separate role are implementation choices supporting the existing operator
boundary, not new product authorization.

A complete downgrade removes product objects, the Auth trigger, private helpers,
private schema, all three Shoulder roles and their grants/memberships. Only the
empty Alembic version table and its `app` schema remain, owned by the migration
connection. Re-upgrade requires reprovisioning passwords. Do not run destructive
migration/isolation tests against a populated development workspace: their
fixtures require a disposable database.
