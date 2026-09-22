"""Coach playback transcode and timeline sprites.

Tasks 11 and 12. Everything here runs inside the CPU worker, never in a
request. Two handlers are registered with `services/worker/main.py`:

- `transcode` probes the original and writes one coach-only, fast-start,
  progressive 720p H.264/AAC MP4 with roughly two-second keyframes
  (`docs/decisions/0001-progressive-mp4-and-isolated-player-clips.md`). There is
  no HLS, no manifest, and no second rendition.
- `thumbnail` writes bounded, deterministically laid out sprite sheets plus the
  timestamp index at `thumbs/{video_id}/index.json`.

Safety rules this module exists to keep (`docs/10-security-privacy.md`):

- ffmpeg and ffprobe are executed as argument arrays with `shell=False`, closed
  stdin, a wall-clock deadline, and a bounded thread count.
- Every path is inside one `mkdtemp` directory that is removed when the handler
  returns, and every object key is derived from the video's UUID.
- Nothing a coach supplied — filename, declared MIME type, container metadata —
  reaches an argument, a path, or a key. `-map_metadata -1` also stops the
  source file's own metadata (camera model, location, original filename) from
  being copied into an object the browser will hold.
- Failures raise `MediaError`, whose message is fixed, coach-safe text. No
  ffmpeg output, storage key, or signed URL is ever stored or logged.
"""

import hashlib
import json
import logging
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from services.api import storage
from services.timeline import (
    COLUMNS as SPRITE_COLUMNS,
)
from services.timeline import (
    ROWS as SPRITE_ROWS,
)
from services.timeline import (
    TILE_HEIGHT,
    TILE_WIDTH,
    SpriteLayout,
    sprite_layout,
)
from services.worker import jobs
from services.worker.jobs import Cancelled

logger = logging.getLogger("shoulder.worker.media")

# --- Output profile. One progressive rendition; ADR 0001 forbids adding a
# second one or a manifest without a new ADR.
TARGET_SHORT_EDGE = 720
TARGET_LONG_EDGE = 1280
KEYFRAME_SECONDS = 2

# --- Startup cost. A browser cannot show frame one of a progressive MP4 until
# it has read the whole `moov` index, and `moov` grows with the sample count,
# not the bitrate: `stsz`, `stco`, `stsc`, and `ctts` all carry per-sample or
# per-chunk entries. Measured on a 90-minute 720p30 match, the naive settings
# index to about 5.7 MB, which spends most of the 2.5-second first-frame budget
# in `docs/02-architecture.md` before a single frame is decoded.
#
# Two settings below halve that, and both are measured in
# `tests/test_media.py::StartupIndexTests`:
#
# - No B-frames. B-frames need a `ctts` composition-offset entry per sample
#   (~1.0 MB at 90 minutes). Dropping them also removes reorder latency from
#   every scrub, which is what this player does constantly, and costs about 4%
#   bitrate at the same CRF.
# - 32 kHz audio. AAC frames are always 1024 samples, so the frame count -- and
#   with it `stsz`/`stco`/`stsc` -- follows the sample rate. 32 kHz is also the
#   rate whose 31.25 frames per second beats cleanly against 30 fps video, so
#   the muxer's chunk pattern becomes periodic and `stsc` collapses from ~1.7 MB
#   to ~0.15 MB. Neither 44.1 kHz (no collapse) nor 22.05 kHz (fewer samples but
#   no collapse) does better, and 32 kHz keeps 16 kHz of audio bandwidth, well
#   above what field audio and coach speech occupy.
#
# Together: about 2.8 MB at 90 minutes. A fragmented layout
# (`+frag_keyframe+empty_moov+global_sidx`) would cut the startup index to
# roughly 55 KB regardless of duration, but was measured and rejected: WebKit
# then seeks only to fragment boundaries, so a one-second arrow-key step lands
# on the previous keyframe instead. Sub-keyframe seek accuracy matters more here
# than the remaining megabytes.
NO_B_FRAMES = "0"
AUDIO_SAMPLE_RATE = "32000"
VIDEO_CRF = "23"
VIDEO_PRESET = "veryfast"
AUDIO_BITRATE = "128k"
PLAYBACK_CONTENT_TYPE = "video/mp4"
CLIP_DURATION_TOLERANCE_MS = 100

# --- Bounds. A file outside these is refused rather than processed: an hours
# long or absurdly large input is either a mistake or an attack on worker time.
MAX_DURATION_MS = 4 * 60 * 60 * 1000
MAX_SOURCE_EDGE = 8192
PROBE_TIMEOUT_SECONDS = 60
# Wall clock for one encode. Generous, because the lease is kept alive by
# heartbeats and the real bound on runaway work is this deadline plus the
# queue's attempt ceiling.
MIN_ENCODE_TIMEOUT_SECONDS = 900
ENCODE_TIMEOUT_FACTOR = 6
ENCODE_THREADS = "2"
# `docs/02-architecture.md`: "The worker heartbeats during ffmpeg work." A tool
# that stalls without writing a line must still be checked this often, so a
# dead or hung process cannot hold the job's lease past its heartbeat window.
POLL_SECONDS = 5.0

# --- Sprite output. The geometry itself lives in `services/timeline.py`,
# because the API has to describe the same layout without rendering it.
SPRITE_CONTENT_TYPE = "image/jpeg"
INDEX_CONTENT_TYPE = "application/json"


class MediaError(Exception):
    """Media work failed. The message is fixed, coach-safe text."""


# --- Tooling ---------------------------------------------------------------


def _tool(name: str) -> str:
    """Locate a pinned binary without ever consulting a request value.

    Order: an explicit environment override (the worker image sets it), then
    the repository's gitignored `.tools/ffmpeg`, then `PATH`. The version and
    checksum in use are recorded in the block's verification record.
    """
    override = os.environ.get(f"{name.upper()}_BINARY")
    if override:
        return override
    suffix = ".exe" if os.name == "nt" else ""
    local = Path(__file__).resolve().parents[2] / ".tools" / "ffmpeg" / (name + suffix)
    if local.is_file():
        return str(local)
    found = shutil.which(name)
    if not found:
        raise MediaError("The video tools are not available on this worker.")
    return found


def ffmpeg_available() -> bool:
    try:
        _tool("ffmpeg")
        _tool("ffprobe")
    except MediaError:
        return False
    return True


def _run(argv: list[str], timeout: int) -> str:
    """One tool invocation: no shell, no stdin, bounded time, captured output.

    Only stdout is captured (ffprobe's small JSON report); stderr is discarded
    rather than buffered, so a tool that writes a large or unbounded amount of
    diagnostic text there cannot grow this process's memory.
    """
    try:
        finished = subprocess.run(  # noqa: S603 - fixed argv, shell=False
            argv,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise MediaError("Preparing this video took too long.") from None
    except OSError:
        raise MediaError("The video tools are not available on this worker.") from None
    if finished.returncode != 0:
        # The tool's stderr can quote the input path; it is logged at debug
        # level nowhere and never stored. Only the exit status is recorded.
        logger.warning("%s exited %s", Path(argv[0]).name, finished.returncode)
        raise MediaError("Shoulder could not read this video file.")
    return finished.stdout


# --- Probe -----------------------------------------------------------------


@dataclass(frozen=True)
class Probe:
    """What the bytes actually are, which is the only thing worth trusting."""

    duration_ms: int
    width: int
    height: int
    fps: float
    has_audio: bool


def _rational(value: Any) -> float:
    """`30000/1001` or `29.97` to a float; anything else is 0."""
    try:
        text_value = str(value)
        if "/" in text_value:
            numerator, _, denominator = text_value.partition("/")
            divisor = float(denominator)
            return float(numerator) / divisor if divisor else 0.0
        return float(text_value)
    except (TypeError, ValueError):
        return 0.0


def _display_size(stream: dict[str, Any]) -> tuple[int, int]:
    """Coded size with the display matrix applied, as a player would show it.

    ffmpeg autorotates on input, so a portrait phone clip stored as 1920x1080
    with a 90-degree matrix must be planned as 1080x1920 or the scale filter
    would stretch it.
    """
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    rotation = 0.0
    for side in stream.get("side_data_list") or []:
        if "rotation" in side:
            rotation = _rational(side["rotation"])
    if round(abs(rotation)) % 180 == 90:
        return height, width
    return width, height


def probe(path: str) -> Probe:
    """Read the container safely. Extension and browser MIME are hints only."""
    raw = _run(
        [
            _tool("ffprobe"),
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            "-i",
            path,
        ],
        PROBE_TIMEOUT_SECONDS,
    )
    try:
        parsed = json.loads(raw)
    except ValueError:
        raise MediaError("Shoulder could not read this video file.") from None
    streams = parsed.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise MediaError("That file does not contain a video track.")
    width, height = _display_size(video)
    if width <= 0 or height <= 0:
        raise MediaError("That file does not contain a video track.")
    if width > MAX_SOURCE_EDGE or height > MAX_SOURCE_EDGE:
        raise MediaError("That video's frame size is larger than Shoulder accepts.")

    duration = _rational((parsed.get("format") or {}).get("duration"))
    if duration <= 0:
        duration = _rational(video.get("duration"))
    duration_ms = int(round(duration * 1000))
    if duration_ms <= 0:
        raise MediaError("Shoulder could not measure this video's length.")
    if duration_ms > MAX_DURATION_MS:
        raise MediaError("That video is longer than Shoulder accepts.")

    fps = _rational(video.get("avg_frame_rate")) or _rational(video.get("r_frame_rate"))
    # A variable-frame-rate phone clip reports an average; a broken one reports
    # nothing. Either way the stored value is only descriptive.
    fps = round(fps, 3) if 0 < fps <= 1000 else 0.0
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    return Probe(
        duration_ms=duration_ms,
        width=width,
        height=height,
        fps=fps,
        has_audio=has_audio,
    )


def playback_size(width: int, height: int) -> tuple[int, int]:
    """720p within the aspect-ratio rules, never upscaling.

    The short edge is capped at 720 and the long edge at 1280, so a portrait or
    ultrawide source stays inside a bounded frame instead of producing a
    2560-pixel-wide "720p" file. Both edges are even, which H.264 4:2:0 needs.
    """
    short = min(width, height)
    long_edge = max(width, height)
    scale = min(1.0, TARGET_SHORT_EDGE / short, TARGET_LONG_EDGE / long_edge)
    return _even(width * scale), _even(height * scale)


def _even(value: float) -> int:
    """Round down to an even number, never up.

    H.264 4:2:0 needs even dimensions, but rounding to the *nearest* even value
    would upscale a source already close to the cap: 1279x719 would become
    1280x720. `playback_size` promises never to upscale, so this floors.
    """
    return max(2, int(value // 2) * 2)


# --- Transcode -------------------------------------------------------------

Progress = Callable[[float | None], bool]


def transcode(source: str, destination: str, media: Probe, report: Progress) -> None:
    """Write the one coach playback rendition.

    `report` is the worker's `keep_going`: it heartbeats the lease and answers
    False when the job was cancelled or the worker is stopping. This kills
    ffmpeg immediately rather than finishing a file nobody wants.
    """
    width, height = playback_size(media.width, media.height)
    audio = (
        [
            "-map",
            "0:a:0?",
            "-c:a",
            "aac",
            "-b:a",
            AUDIO_BITRATE,
            "-ac",
            "2",
            # Sample rate drives the AAC frame count, and the frame count drives
            # the startup index. See the startup-cost note above.
            "-ar",
            AUDIO_SAMPLE_RATE,
        ]
        if media.has_audio
        else ["-an"]
    )
    argv = [
        _tool("ffmpeg"),
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-threads",
        ENCODE_THREADS,
        "-i",
        source,
        "-map",
        "0:v:0",
        *audio,
        # Camera model, GPS, and the original filename never reach the object.
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
        "-c:v",
        "libx264",
        "-preset",
        VIDEO_PRESET,
        "-crf",
        VIDEO_CRF,
        "-profile:v",
        "high",
        # No `ctts` table, and no reorder latency on a scrub. See the
        # startup-cost note above.
        "-bf",
        NO_B_FRAMES,
        "-pix_fmt",
        "yuv420p",
        "-vf",
        f"scale={width}:{height}",
        # Time-based, so a variable-frame-rate source still gets a keyframe
        # about every two seconds. That is what makes a random seek cheap.
        "-force_key_frames",
        f"expr:gte(t,n_forced*{KEYFRAME_SECONDS})",
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        "-progress",
        "pipe:1",
        "-nostats",
        destination,
    ]
    _encode(argv, media.duration_ms, report)


def _seconds(milliseconds: int) -> str:
    return f"{milliseconds / 1000:.3f}"


def clip_command(
    source: str,
    destination: str,
    start_ms: int,
    end_ms: int,
    has_audio: bool,
) -> list[str]:
    """Exact-boundary re-encode command for one isolated player clip."""
    if start_ms < 0 or end_ms <= start_ms:
        raise MediaError("The requested clip boundaries are invalid.")
    audio = (
        [
            "-map",
            "0:a:0?",
            "-c:a",
            "aac",
            "-b:a",
            AUDIO_BITRATE,
            "-ac",
            "2",
            "-ar",
            AUDIO_SAMPLE_RATE,
        ]
        if has_audio
        else ["-an"]
    )
    return [
        _tool("ffmpeg"),
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-threads",
        ENCODE_THREADS,
        "-i",
        source,
        # Output-side seek decodes up to the selected frame. Input-side seek
        # could start at an earlier keyframe and expose unapproved context.
        "-ss",
        _seconds(start_ms),
        "-t",
        _seconds(end_ms - start_ms),
        "-map",
        "0:v:0",
        *audio,
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
        "-c:v",
        "libx264",
        "-preset",
        VIDEO_PRESET,
        "-crf",
        VIDEO_CRF,
        "-profile:v",
        "high",
        "-bf",
        NO_B_FRAMES,
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        destination,
    ]


def export_clip(
    source: str,
    destination: str,
    start_ms: int,
    end_ms: int,
    report: Progress,
) -> Probe:
    """Re-encode and verify an isolated clip at the requested boundaries."""
    source_probe = probe(source)
    if end_ms > source_probe.duration_ms + CLIP_DURATION_TOLERANCE_MS:
        raise MediaError("The requested clip boundaries are invalid.")
    argv = clip_command(source, destination, start_ms, end_ms, source_probe.has_audio)
    _run_with_heartbeat(
        argv,
        max(MIN_ENCODE_TIMEOUT_SECONDS, (end_ms - start_ms) // 1000 * 6),
        report,
    )
    result = probe(destination)
    expected = end_ms - start_ms
    if abs(result.duration_ms - expected) > CLIP_DURATION_TOLERANCE_MS:
        raise MediaError("Shoulder could not preserve the selected clip boundaries.")
    return result


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _out_time_fraction(line: str, duration_ms: int) -> float | None:
    """One `-progress pipe:1` line to a bounded fraction, or None if it is not

    the `out_time_us` line. No ffmpeg text is stored, logged, or forwarded;
    only this one bounded number ever reaches `report`.
    """
    if not line.startswith("out_time_us="):
        return None
    done = _rational(line.split("=", 1)[1].strip()) / 1000.0
    return min(1.0, max(0.0, done / duration_ms)) if duration_ms else 0.0


def _encode(argv: list[str], duration_ms: int, report: Progress) -> None:
    """Run ffmpeg, forwarding sanitized progress and honouring cancellation."""
    timeout = max(
        MIN_ENCODE_TIMEOUT_SECONDS, duration_ms // 1000 * ENCODE_TIMEOUT_FACTOR
    )
    _run_with_heartbeat(
        argv,
        timeout,
        report,
        parse_progress=lambda line: _out_time_fraction(line, duration_ms),
    )


def _run_with_heartbeat(
    argv: list[str],
    timeout: int,
    report: Progress,
    parse_progress: Callable[[str], float | None] | None = None,
) -> None:
    """Run one tool, polling so a heartbeat and the deadline both run even if

    the tool blocks without writing anything. `docs/02-architecture.md`: "The
    worker heartbeats during ffmpeg work." A plain `for line in process.stdout`
    blocks until a line arrives, so a stalled tool would silently hold the
    lease; reading through a background thread and a queue with a bounded
    `get` timeout means this loop always wakes up at least every
    `POLL_SECONDS` to call `report` and check the deadline.

    `parse_progress`, given for the transcode's `-progress pipe:1` output,
    turns one stdout line into a fraction; every line still triggers a
    liveness `report(None)` when it is not a progress line, matching what a
    line-at-a-time reader always did. Without it (sprite generation has no
    machine-readable progress), stdout is discarded and only the poll
    interval reports liveness.
    """
    deadline = time.monotonic() + timeout
    try:
        process = subprocess.Popen(  # noqa: S603 - fixed argv, shell=False
            argv,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if parse_progress else subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError:
        raise MediaError("The video tools are not available on this worker.") from None

    lines: queue.Queue[str | None] | None = None
    reader: threading.Thread | None = None
    if parse_progress is not None:
        assert process.stdout is not None
        stdout = process.stdout
        lines = queue.Queue()
        pending = lines

        def _read() -> None:
            try:
                for raw_line in stdout:
                    pending.put(raw_line)
            finally:
                pending.put(None)  # end-of-stream sentinel

        reader = threading.Thread(target=_read, daemon=True)
        reader.start()

    try:
        while True:
            if lines is not None:
                try:
                    line = lines.get(timeout=POLL_SECONDS)
                except queue.Empty:
                    if not report(None):
                        raise _Stopped
                    line = ""
                if line is None:
                    break
                if line:
                    fraction = parse_progress(line) if parse_progress else None
                    ok = (
                        report(round(fraction, 3))
                        if fraction is not None
                        else report(None)
                    )
                    if not ok:
                        raise _Stopped
            else:
                try:
                    process.wait(timeout=POLL_SECONDS)
                    break
                except subprocess.TimeoutExpired:
                    if not report(None):
                        raise _Stopped
            if time.monotonic() > deadline:
                raise MediaError("Preparing this video took too long.")
    except _Stopped:
        _terminate(process)
        raise Cancelled from None
    except MediaError:
        _terminate(process)
        raise
    finally:
        if process.stdout is not None:
            process.stdout.close()
        if reader is not None:
            reader.join(timeout=30)
    if process.wait() != 0:
        logger.warning("%s exited %s", Path(argv[0]).name, process.returncode)
        raise MediaError("Shoulder could not prepare this video.")


class _Stopped(Exception):
    """Internal: `keep_going()` said stop."""


def _terminate(process: "subprocess.Popen[str]") -> None:
    process.kill()
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:  # pragma: no cover - kill does not hang
        logger.warning("a media tool did not exit after being killed")


# --- Sprite timeline -------------------------------------------------------


def sprite_sheets(
    source: str, directory: str, layout: SpriteLayout, report: Progress
) -> list[Path]:
    """Render the sheets. Every tile is letterboxed into the same fixed box."""
    pattern = str(Path(directory) / "sprite-%d.jpg")
    argv = [
        _tool("ffmpeg"),
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-threads",
        ENCODE_THREADS,
        "-i",
        source,
        "-map",
        "0:v:0",
        "-an",
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
        "-vf",
        (
            f"fps=fps=1000/{layout.interval_ms},"
            f"scale={TILE_WIDTH}:{TILE_HEIGHT}:force_original_aspect_ratio=decrease,"
            f"pad={TILE_WIDTH}:{TILE_HEIGHT}:(ow-iw)/2:(oh-ih)/2,"
            f"tile={SPRITE_COLUMNS}x{SPRITE_ROWS}"
        ),
        # The layout is authoritative: a source that yields one extra frame
        # must not silently produce a fifth sheet the index does not describe.
        "-frames:v",
        str(layout.sheet_count),
        "-q:v",
        "5",
        "-start_number",
        "0",
        "-f",
        "image2",
        pattern,
    ]
    _run_with_heartbeat(
        argv, max(MIN_ENCODE_TIMEOUT_SECONDS, PROBE_TIMEOUT_SECONDS), report
    )
    sheets = sorted(
        (path for path in Path(directory).glob("sprite-*.jpg")),
        key=lambda path: int(path.stem.rsplit("-", 1)[1]),
    )
    if not sheets:
        raise MediaError("Shoulder could not build this video's timeline.")
    return sheets


def index_document(layout: SpriteLayout, sheets: int) -> dict[str, Any]:
    """The timestamp index. Content-free: geometry and timing only."""
    return {
        "version": 1,
        "tile_width": layout.tile_width,
        "tile_height": layout.tile_height,
        "columns": layout.columns,
        "rows": layout.rows,
        "interval_ms": layout.interval_ms,
        "tile_count": layout.tile_count,
        "sheet_count": sheets,
    }


# --- Database --------------------------------------------------------------
#
# The worker connects as `shoulder_worker` (ADR 0018): no user identity, and
# column-level UPDATE grants that reach exactly the probe and playback columns.


def _load(connection: Connection, video_id: UUID) -> Any:
    return connection.execute(
        text(
            "SELECT id, original_key, status, playback_key, duration_ms"
            " FROM app.video WHERE id = :id"
        ),
        {"id": str(video_id)},
    ).one_or_none()


def _start(connection: Connection, video_id: UUID) -> int:
    """`uploaded` -> `processing`. Re-entrant: a retry re-claims its own row."""
    return connection.execute(
        text(
            "UPDATE app.video SET status = 'processing'"
            " WHERE id = :id AND status IN ('uploaded', 'processing')"
        ),
        {"id": str(video_id)},
    ).rowcount


def _finish(connection: Connection, video_id: UUID, key: str, media: Probe) -> int:
    return connection.execute(
        text("""
            UPDATE app.video SET
                playback_key = :playback_key,
                duration_ms = :duration_ms,
                width = :width,
                height = :height,
                fps = :fps,
                status = 'ready',
                ready_at = now()
            WHERE id = :id AND status = 'processing'
        """),
        {
            "id": str(video_id),
            "playback_key": key,
            "duration_ms": media.duration_ms,
            "width": media.width,
            "height": media.height,
            "fps": media.fps or None,
            # Only these columns are grantable to the worker, so a bug here
            # cannot retarget the object key or reopen an upload.
        },
    ).rowcount


def _mark_failed(video_id: UUID) -> None:
    """Terminal, coach-visible state once the queue has no attempts left.

    `first_terminal_failure_at` is the deadline `docs/10-security-privacy.md`
    measures rejected-media cleanup from, and is set once.
    """
    with jobs.transaction() as connection:
        connection.execute(
            text("""
                UPDATE app.video SET
                    status = 'failed',
                    first_terminal_failure_at =
                        coalesce(first_terminal_failure_at, now())
                WHERE id = :id AND status IN ('uploaded', 'processing')
            """),
            {"id": str(video_id)},
        )


# --- Handlers --------------------------------------------------------------


def transcode_job(job: jobs.Job, keep_going: Progress) -> None:
    """Task 11. One original in, one coach playback object out."""
    video_id = job.video_id
    if video_id is None:
        raise MediaError("This job has no video to prepare.")
    try:
        with jobs.transaction() as connection:
            row = _load(connection, video_id)
            if row is None or row.status in ("deleted", "deletion_pending", "failed"):
                # The coach abandoned or deleted it while the job waited. Doing
                # the work anyway would resurrect an object that must not exist.
                return
            if row.status == "ready" and row.playback_key:
                return
            if row.status not in ("uploaded", "processing"):
                return
            _start(connection, video_id)
            source_key = row.original_key

        key = storage.playback_key(video_id)
        with _workspace() as directory:
            source = str(Path(directory) / "source")
            output = str(Path(directory) / "coach-720p.mp4")
            try:
                storage.download_object(source_key, source, report=keep_going)
            except storage.TransferAborted:
                raise Cancelled from None
            if not keep_going(0.0):
                raise Cancelled
            media = probe(source)
            transcode(source, output, media, keep_going)
            if not keep_going(0.99):
                raise Cancelled
            # Probe the output, not the source. The coach player sizes its
            # frame and its scrubber from these columns, and they have to
            # describe the object it actually loads, which is the 720p file
            # rather than the original. Duration comes from the same probe, so
            # a transcode that truncated the match cannot report the source's
            # full length and leave the scrubber running past the end.
            played = probe(output)
            try:
                storage.upload_object(
                    key, output, PLAYBACK_CONTENT_TYPE, report=keep_going
                )
            except storage.TransferAborted:
                raise Cancelled from None
            # The upload can outlast several heartbeat intervals; check the
            # lease is still ours and the job is not cancelled before writing
            # the `ready` row, so a job that lost its lease mid-upload cannot
            # finalize a video another attempt is also working on.
            if not keep_going(1.0):
                raise Cancelled

        with jobs.transaction() as connection:
            finished = _finish(connection, video_id, key, played)
        if not finished:
            _discard_video_derivatives_if_deleting(video_id)
    except Cancelled:
        _discard_video_derivatives_if_deleting(video_id)
        raise
    except (MediaError, storage.StorageError):
        _fail_if_final(job, video_id)
        raise


def thumbnail_job(job: jobs.Job, keep_going: Progress) -> None:
    """Task 12. Sprite sheets and the timestamp index for the scrubber.

    Deliberately independent of `transcode`: it reads the original rather than
    the playback object, so neither job has to wait for the other and a slow
    encode cannot exhaust this job's attempts.

    ponytail: full decode of the original. `-skip_frame nokey` would be far
    faster; add it when a source's keyframe spacing is known to be finer than
    the sprite interval, otherwise the tile count stops being deterministic.
    """
    video_id = job.video_id
    if video_id is None:
        raise MediaError("This job has no video to prepare.")
    try:
        with jobs.transaction() as connection:
            row = _load(connection, video_id)
            if row is None or row.status in (
                "deleted",
                "deletion_pending",
                "failed",
                "uploading",
            ):
                return
            source_key = row.original_key

        with _workspace() as directory:
            source = str(Path(directory) / "source")
            try:
                storage.download_object(source_key, source, report=keep_going)
            except storage.TransferAborted:
                raise Cancelled from None
            if not keep_going(0.0):
                raise Cancelled
            media = probe(source)
            layout = sprite_layout(media.duration_ms)
            sheets = sprite_sheets(source, directory, layout, keep_going)
            if not keep_going(0.8):
                raise Cancelled
            try:
                for number, sheet in enumerate(sheets):
                    storage.upload_object(
                        storage.sprite_key(video_id, number),
                        str(sheet),
                        SPRITE_CONTENT_TYPE,
                        report=keep_going,
                    )
                index = Path(directory) / "index.json"
                index.write_text(
                    json.dumps(index_document(layout, len(sheets))), encoding="utf-8"
                )
                storage.upload_object(
                    storage.thumbnail_index_key(video_id),
                    str(index),
                    INDEX_CONTENT_TYPE,
                    report=keep_going,
                )
                if not keep_going(1.0):
                    raise Cancelled
            except storage.TransferAborted:
                raise Cancelled from None
    except Cancelled:
        _discard_video_derivatives_if_deleting(video_id)
        raise
    except (MediaError, storage.StorageError):
        # A missing timeline does not make a video unwatchable, so this never
        # marks the video failed; the job row carries the failure.
        raise


def clip_export_job(job: jobs.Job, keep_going: Progress) -> None:
    """Export one revision-pinned object and attach it through fenced SQL."""
    with jobs.transaction() as connection:
        export = connection.execute(
            text("SELECT * FROM private.clip_export_input(:job_id, :worker_id)"),
            {"job_id": str(job.id), "worker_id": job.locked_by},
        ).one_or_none()
    if export is None:
        return

    uploaded = False
    try:
        with _workspace() as directory:
            source = str(Path(directory) / "coach-playback.mp4")
            output = str(Path(directory) / "evidence.mp4")
            try:
                storage.download_object(export.source_key, source, report=keep_going)
            except storage.TransferAborted:
                raise Cancelled from None
            if not keep_going(0.05):
                raise Cancelled
            result = export_clip(
                source,
                output,
                export.clip_start_ms,
                export.clip_end_ms,
                keep_going,
            )
            if not keep_going(0.9):
                raise Cancelled
            try:
                storage.upload_object(
                    export.target_key,
                    output,
                    PLAYBACK_CONTENT_TYPE,
                    report=keep_going,
                )
            except storage.TransferAborted:
                raise Cancelled from None
            uploaded = True
            if not keep_going(0.98):
                raise Cancelled
            with jobs.transaction() as connection:
                attached = bool(
                    connection.execute(
                        text("""
                            SELECT private.complete_evidence_clip(
                                :job_id, :worker_id, :duration_ms,
                                :size_bytes, :sha256
                            )
                        """),
                        {
                            "job_id": str(job.id),
                            "worker_id": job.locked_by,
                            "duration_ms": result.duration_ms,
                            "size_bytes": os.path.getsize(output),
                            "sha256": file_sha256(output),
                        },
                    ).scalar_one()
                )
            if not attached:
                _discard_own_clip_object(job, export.target_key)
                uploaded = False
    except Cancelled:
        if uploaded:
            try:
                _discard_own_clip_object(job, export.target_key)
            except storage.StorageError:
                pass
        raise


def _discard_own_clip_object(job: jobs.Job, target_key: str) -> None:
    """Remove this attempt's upload, but only while it is still this attempt's.

    A clip's storage key is derived from its judgment and clip version, so a
    job retried against the same clip row uploads to the same key as the
    attempt it replaced. Deleting unconditionally on the way out would take
    the replacement's finished clip with it, leaving a publication pointing at
    an object that is no longer there.

    Asking whether the key is unused is not enough on its own, because the
    answer is read in one transaction and the delete happens after it commits:
    a replacement can finish inside that window and lose its clip anyway. The
    lease is what actually settles ownership. A worker that still holds this
    job holds it exclusively, so no replacement exists to race with; a worker
    that has lost it has no business deleting a key somebody else now owns,
    and leaves the object to be reused or to expire on its deadline.
    """
    with jobs.transaction() as connection:
        disposable = bool(
            connection.execute(
                text("""
                    SELECT private.evidence_clip_object_disposable(
                        :job_id, :worker_id, :key
                    )
                """),
                {
                    "job_id": str(job.id),
                    "worker_id": job.locked_by,
                    "key": target_key,
                },
            ).scalar_one()
        )
    if disposable:
        storage.delete_object(target_key)


def _fail_if_final(job: jobs.Job, video_id: UUID) -> None:
    """Tell the coach the truth once the queue has stopped retrying."""
    if job.attempts >= job.max_attempts:
        _mark_failed(video_id)


def _discard_video_derivatives_if_deleting(video_id: UUID) -> None:
    """Remove a late worker write only after the database fences the video."""
    with jobs.transaction() as connection:
        status = connection.execute(
            text("SELECT status FROM app.video WHERE id = :video_id"),
            {"video_id": str(video_id)},
        ).scalar_one_or_none()
    if status not in (None, "deletion_pending", "deleted"):
        return
    keys = [
        storage.playback_key(video_id),
        storage.thumbnail_index_key(video_id),
        *(storage.sprite_key(video_id, sheet) for sheet in range(4)),
    ]
    for key in keys:
        try:
            storage.delete_object(key)
        except storage.StorageError:
            # The durable deletion manifest retries and verifies every key.
            pass


class _Workspace:
    """A task-scoped directory, removed whether the handler succeeds or not.

    `docs/10-security-privacy.md`: task-local media is deleted at task end.
    """

    def __enter__(self) -> str:
        self.path = tempfile.mkdtemp(prefix="shoulder-media-")
        return self.path

    def __exit__(self, *_: object) -> None:
        shutil.rmtree(self.path, ignore_errors=True)


def _workspace() -> _Workspace:
    return _Workspace()


HANDLERS: dict[str, Any] = {
    "transcode": transcode_job,
    "thumbnail": thumbnail_job,
    "clip_export": clip_export_job,
}
