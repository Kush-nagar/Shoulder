"""Worker write access to the probe and coach playback columns

Revision ID: 0006_media_playback
Revises: 0005_video_ingest

Migration `0005` created `app.video.playback_key`, `duration_ms`, `width`,
`height`, and `fps` as nullable columns nothing was allowed to write, and gave
`shoulder_worker` `UPDATE (status, ready_at)` only. Task 11 is the first code
that produces those values, so this migration widens exactly that grant and
nothing else.

`first_terminal_failure_at` is included because the transcode handler is what
learns that a video can never be prepared, and
`docs/10-security-privacy.md` measures rejected-media cleanup from that stamp.

Deliberately still not granted to the worker: `original_key` and `playback_key`
are the two columns that decide which object a signed URL can name.
`original_key` has no UPDATE grant on any runtime role. `playback_key` is
granted here because the worker is what creates that object, but the API never
reads a key from a request and derives the playback key from the video's UUID,
so a bad value in that column cannot retarget a coach URL.

No table, policy, or index changes, so RLS is unchanged: `app.video` keeps
forced row-level security and the `video_worker_*` policies from `0005`.
"""

from alembic import op

revision = "0006_media_playback"
down_revision = "0005_video_ingest"
branch_labels = None
depends_on = None

WORKER_ROLE = "shoulder_worker"
WORKER_COLUMNS = (
    "playback_key",
    "duration_ms",
    "width",
    "height",
    "fps",
    "first_terminal_failure_at",
)


def upgrade() -> None:
    op.execute(
        f"GRANT UPDATE ({', '.join(WORKER_COLUMNS)}) ON app.video TO {WORKER_ROLE}"
    )


def downgrade() -> None:
    # Column-level revoke, so `status` and `ready_at` from `0005` survive
    # exactly as they were.
    op.execute(
        f"REVOKE UPDATE ({', '.join(WORKER_COLUMNS)}) ON app.video FROM {WORKER_ROLE}"
    )
