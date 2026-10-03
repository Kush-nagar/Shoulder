"""Wake the GitHub Actions worker when work is queued (ADR 0028)

Revision ID: 0021_worker_wake
Revises: 0020_coach_marketplace

The CPU worker no longer runs as an always-on machine. A statement-level
trigger on `app.processing_job` asks GitHub to start the worker workflow
(`repository_dispatch`, event `worker`) through `pg_net`, which queues the
request and sends it after commit, so enqueueing never waits on or fails
because of GitHub. The token lives in Supabase Vault as
`worker_dispatch_token`; without it (local stacks, CI) the trigger does nothing.

The function sits in its own `worker_wake` schema, not `private`, because it
must be owned by `postgres` to read Vault and call `net.http_post`. It reads no
row data, takes no argument, and nobody but the trigger can run it.
"""

# ruff: noqa: E501 -- SQL stays aligned with the reviewed database statements.

from alembic import op

revision = "0021_worker_wake"
down_revision = "0020_coach_marketplace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'pg_net') THEN
                CREATE EXTENSION IF NOT EXISTS pg_net;
            END IF;
        END
        $$
    """)
    op.execute("CREATE SCHEMA worker_wake")
    op.execute("REVOKE ALL ON SCHEMA worker_wake FROM PUBLIC")
    op.execute("""
        CREATE FUNCTION worker_wake.dispatch() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE
            v_token text;
            v_repo text;
        BEGIN
            IF to_regclass('vault.decrypted_secrets') IS NULL
               OR to_regnamespace('net') IS NULL THEN
                RETURN NULL;
            END IF;
            EXECUTE 'SELECT decrypted_secret FROM vault.decrypted_secrets WHERE name = $1'
                INTO v_token USING 'worker_dispatch_token';
            IF v_token IS NULL OR v_token = '' THEN
                RETURN NULL;
            END IF;
            EXECUTE 'SELECT decrypted_secret FROM vault.decrypted_secrets WHERE name = $1'
                INTO v_repo USING 'worker_dispatch_repo';
            EXECUTE 'SELECT net.http_post(url := $1, body := $2, headers := $3)'
                USING
                    'https://api.github.com/repos/'
                        || coalesce(nullif(v_repo, ''), 'Kush-nagar/Shoulder')
                        || '/dispatches',
                    jsonb_build_object('event_type', 'worker'),
                    jsonb_build_object(
                        'Authorization', 'Bearer ' || v_token,
                        'Accept', 'application/vnd.github+json',
                        'X-GitHub-Api-Version', '2022-11-28',
                        'User-Agent', 'shoulder-worker-wake',
                        'Content-Type', 'application/json'
                    );
            RETURN NULL;
        EXCEPTION WHEN OTHERS THEN
            -- A wake-up is best effort: the scheduled run is the safety net.
            RAISE WARNING 'worker wake-up skipped (%)', SQLSTATE;
            RETURN NULL;
        END
        $$
    """)
    op.execute("REVOKE ALL ON FUNCTION worker_wake.dispatch() FROM PUBLIC")
    op.execute("""
        CREATE TRIGGER processing_job_wake_worker
        AFTER INSERT ON app.processing_job
        FOR EACH STATEMENT EXECUTE FUNCTION worker_wake.dispatch()
    """)


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS processing_job_wake_worker ON app.processing_job"
    )
    op.execute("DROP FUNCTION IF EXISTS worker_wake.dispatch()")
    op.execute("DROP SCHEMA IF EXISTS worker_wake")
    # pg_net stays installed: other Supabase features may use it.
