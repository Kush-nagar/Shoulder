"""Do not wake the worker for retention sweeps (ADR 0028)

Revision ID: 0022_worker_wake_skip_sweeps
Revises: 0021_worker_wake

Each worker run enqueues a retention sweep, so waking the worker for that
insert would start the next run, which enqueues the next sweep, forever. The
trigger now reads the inserted rows through a transition table and wakes the
worker only when real work arrived. The 6-hourly scheduled run still sweeps.
"""

# ruff: noqa: E501 -- SQL stays aligned with the reviewed database statements.

from alembic import op

revision = "0022_worker_wake_skip_sweeps"
down_revision = "0021_worker_wake"
branch_labels = None
depends_on = None

GUARD = """
            IF NOT EXISTS (
                SELECT 1 FROM inserted_jobs WHERE kind <> 'retention_sweep'
            ) THEN
                RETURN NULL;
            END IF;
"""


def _function(guard: str) -> str:
    return f"""
        CREATE OR REPLACE FUNCTION worker_wake.dispatch() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE
            v_token text;
            v_repo text;
        BEGIN{guard}
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
    """


def upgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS processing_job_wake_worker ON app.processing_job"
    )
    op.execute(_function(GUARD))
    op.execute("REVOKE ALL ON FUNCTION worker_wake.dispatch() FROM PUBLIC")
    op.execute("""
        CREATE TRIGGER processing_job_wake_worker
        AFTER INSERT ON app.processing_job
        REFERENCING NEW TABLE AS inserted_jobs
        FOR EACH STATEMENT EXECUTE FUNCTION worker_wake.dispatch()
    """)


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS processing_job_wake_worker ON app.processing_job"
    )
    op.execute(_function(""))
    op.execute("REVOKE ALL ON FUNCTION worker_wake.dispatch() FROM PUBLIC")
    op.execute("""
        CREATE TRIGGER processing_job_wake_worker
        AFTER INSERT ON app.processing_job
        FOR EACH STATEMENT EXECUTE FUNCTION worker_wake.dispatch()
    """)
