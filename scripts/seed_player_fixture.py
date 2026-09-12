"""Publish a real coach-playback fixture for Task 13's Playwright coverage.

`tests/player.spec.mjs` needs a video that a real browser can actually seek
and scrub, so this generates one with the pinned ffmpeg — never committed
footage, exactly like `tests/test_media.py`'s fixtures — and publishes the
playback object and sprite timeline through the real `services.api.storage`
and `services.worker.media` functions the worker uses in production. The
spec inserts the matching `app.video` row itself, once this prints the
dimensions and timing the row and the test's assertions both need.

Invoked as `python -m scripts.seed_player_fixture --video-id <uuid>` with the
same `R2_*` environment `scripts/check-storage.ps1` sets.
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from uuid import UUID

from services.api import storage
from services.timeline import sprite_layout
from services.worker import media


def generate_source(path: str, seconds: int) -> None:
    """A fast-start 1280x720 H.264/AAC clip with two-second keyframes.

    Already at the coach playback profile, so this stands in directly for a
    transcoded object; the real encoder is `tests/test_media.py`'s concern,
    not this fixture's.
    """
    subprocess.run(
        [
            media._tool("ffmpeg"),
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size=1280x720:rate=30:duration={seconds}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-force_key_frames",
            "expr:gte(t,n_forced*2)",
            "-movflags",
            "+faststart",
            path,
        ],
        check=True,
        capture_output=True,
        # A 90-minute budget fixture (`scripts/check-playback-budget.ps1`)
        # takes real minutes to encode; scale with the requested length rather
        # than pin a constant that only fits the short player-test fixtures.
        timeout=max(120, seconds * 3),
    )


def keep_going(progress: float | None = None) -> bool:
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--seconds", type=int, default=12)
    parser.add_argument(
        "--skip-thumbnails",
        action="store_true",
        help=(
            "Publish only the playback object. The full-length playback-budget"
            " measurement only ever loads the playback route, and the sprite"
            " job's full decode pass would otherwise roughly double a 90-minute"
            " fixture's generation time for no evidence it needs."
        ),
    )
    args = parser.parse_args()
    video_id = UUID(args.video_id)

    result: dict[str, float | int | None] = {}
    with tempfile.TemporaryDirectory(prefix="shoulder-player-fixture-") as directory:
        source = str(Path(directory) / "source.mp4")
        generate_source(source, args.seconds)
        probe = media.probe(source)
        storage.upload_object(
            storage.playback_key(video_id), source, media.PLAYBACK_CONTENT_TYPE
        )
        result = {
            "duration_ms": probe.duration_ms,
            "width": probe.width,
            "height": probe.height,
            "fps": probe.fps,
            "size_bytes": Path(source).stat().st_size,
            "interval_ms": None,
            "sheet_count": None,
        }

        if not args.skip_thumbnails:
            layout = sprite_layout(probe.duration_ms)
            sheets = media.sprite_sheets(source, directory, layout, keep_going)
            for number, sheet in enumerate(sheets):
                storage.upload_object(
                    storage.sprite_key(video_id, number),
                    str(sheet),
                    media.SPRITE_CONTENT_TYPE,
                )
            index_path = Path(directory) / "index.json"
            index_path.write_text(
                json.dumps(media.index_document(layout, len(sheets))),
                encoding="utf-8",
            )
            storage.upload_object(
                storage.thumbnail_index_key(video_id),
                str(index_path),
                media.INDEX_CONTENT_TYPE,
            )
            result["interval_ms"] = layout.interval_ms
            result["sheet_count"] = len(sheets)

    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
