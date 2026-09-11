"""Task 11 and 12 media work, against real ffmpeg and generated fixtures.

`docs/11-testing-quality.md` requires synthetic fixtures generated for the
suite, never committed footage, so every clip here is produced by ffmpeg at
test time and deleted afterwards.

The geometry tests are pure arithmetic and always run. The probe, transcode,
and sprite tests need the pinned ffmpeg and skip cleanly without it; the
configuration test makes that skip impossible to hide where media work is
required.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from services import timeline
from services.worker import media

REQUIRED = os.environ.get("REQUIRE_MEDIA_TESTS", "").lower() in ("1", "true")
AVAILABLE = media.ffmpeg_available()


class ConfigurationTests(unittest.TestCase):
    def test_media_tests_are_configured_where_required(self) -> None:
        """A media job must never pass by skipping the media suite."""
        if REQUIRED:
            self.assertTrue(AVAILABLE, "pinned ffmpeg and ffprobe are required")
            self.assertFalse(
                getattr(TranscodeTests, "__unittest_skip__", False),
                "the transcode suite must run where media work is required",
            )


class PlaybackSizeTests(unittest.TestCase):
    """720p means a bounded frame, not a literal height."""

    def test_landscape_scales_to_720_high(self) -> None:
        self.assertEqual(media.playback_size(1920, 1080), (1280, 720))

    def test_a_portrait_phone_video_stays_inside_the_frame(self) -> None:
        """The naive rule would emit a 1280-wide portrait file; this must not."""
        width, height = media.playback_size(1080, 1920)
        self.assertEqual((width, height), (720, 1280))
        self.assertLessEqual(min(width, height), media.TARGET_SHORT_EDGE)
        self.assertLessEqual(max(width, height), media.TARGET_LONG_EDGE)

    def test_an_ultrawide_source_is_bounded_on_its_long_edge(self) -> None:
        width, height = media.playback_size(3840, 1080)
        self.assertLessEqual(width, media.TARGET_LONG_EDGE)

    def test_a_small_source_is_never_upscaled(self) -> None:
        self.assertEqual(media.playback_size(640, 360), (640, 360))

    def test_every_dimension_is_even(self) -> None:
        """H.264 4:2:0 cannot encode an odd dimension."""
        for source in ((1919, 1079), (1081, 1921), (641, 361), (3, 5)):
            with self.subTest(source=source):
                width, height = media.playback_size(*source)
                self.assertEqual(width % 2, 0)
                self.assertEqual(height % 2, 0)
                self.assertGreaterEqual(min(width, height), 2)


class SpriteGeometryTests(unittest.TestCase):
    """The worker, the API, and the browser all derive this from duration."""

    def test_a_full_match_stays_within_four_sheets(self) -> None:
        layout = timeline.sprite_layout(90 * 60 * 1000)
        self.assertLessEqual(layout.sheet_count, timeline.MAX_SHEETS)
        self.assertLessEqual(layout.tile_count, timeline.MAX_TILES)
        self.assertGreaterEqual(layout.interval_ms, timeline.MIN_INTERVAL_MS)

    def test_a_short_clip_is_never_finer_than_two_seconds(self) -> None:
        layout = timeline.sprite_layout(40 * 1000)
        self.assertEqual(layout.interval_ms, timeline.MIN_INTERVAL_MS)
        self.assertEqual(layout.sheet_count, 1)

    def test_geometry_is_deterministic(self) -> None:
        for duration in (1, 1000, 40_000, 5 * 60_000, 90 * 60_000, 4 * 3600_000):
            with self.subTest(duration=duration):
                self.assertEqual(
                    timeline.sprite_layout(duration), timeline.sprite_layout(duration)
                )

    def test_a_non_positive_duration_is_refused(self) -> None:
        for duration in (0, -1):
            with self.subTest(duration=duration):
                with self.assertRaises(ValueError):
                    timeline.sprite_layout(duration)

    def test_every_tile_lands_on_a_real_sheet(self) -> None:
        duration = 90 * 60 * 1000
        layout = timeline.sprite_layout(duration)
        for time_ms in (0, 1, duration // 2, duration - 1, duration, duration * 2):
            with self.subTest(time_ms=time_ms):
                sheet, column, row = timeline.sprite_position(time_ms, layout)
                self.assertGreaterEqual(sheet, 0)
                self.assertLess(sheet, layout.sheet_count)
                self.assertLess(column, layout.columns)
                self.assertLess(row, layout.rows)

    def test_a_timestamp_past_the_end_clamps_rather_than_overflowing(self) -> None:
        layout = timeline.sprite_layout(60_000)
        last = timeline.sprite_position(60_000, layout)
        self.assertEqual(timeline.sprite_position(10**9, layout), last)


def generate(
    path: Path,
    seconds: int = 3,
    size: str = "320x240",
    audio: bool = True,
    extra: list[str] | None = None,
) -> Path:
    """One synthetic clip. Nothing real is ever committed to the repository."""
    argv = [
        media._tool("ffmpeg"),
        "-nostdin",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=size={size}:rate=15:duration={seconds}",
    ]
    if audio:
        argv += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    argv += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if audio:
        argv += ["-c:a", "aac"]
    argv += (extra or []) + [str(path)]
    subprocess.run(argv, check=True, capture_output=True, timeout=120)
    return path


@unittest.skipUnless(AVAILABLE, "pinned ffmpeg and ffprobe are not available")
class ProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="shoulder-media-"))
        self.addCleanup(self._clean)

    def _clean(self) -> None:
        for child in self.dir.glob("*"):
            child.unlink(missing_ok=True)
        self.dir.rmdir()

    def test_a_generated_clip_probes_to_its_real_properties(self) -> None:
        source = generate(self.dir / "clip.mp4", seconds=3, size="640x480")
        result = media.probe(str(source))
        self.assertAlmostEqual(result.duration_ms, 3000, delta=400)
        self.assertEqual((result.width, result.height), (640, 480))
        self.assertGreater(result.fps, 0)
        self.assertTrue(result.has_audio)

    def test_a_silent_clip_is_recognised_as_silent(self) -> None:
        """`docs/10-security-privacy.md` allows dropping audio entirely."""
        source = generate(self.dir / "silent.mp4", audio=False)
        self.assertFalse(media.probe(str(source)).has_audio)

    def test_a_corrupt_file_is_refused_rather_than_guessed(self) -> None:
        bad = self.dir / "corrupt.mp4"
        bad.write_bytes(b"not a video at all" * 100)
        with self.assertRaises(media.MediaError):
            media.probe(str(bad))

    def test_an_empty_file_is_refused(self) -> None:
        empty = self.dir / "empty.mp4"
        empty.write_bytes(b"")
        with self.assertRaises(media.MediaError):
            media.probe(str(empty))

    def test_a_probe_failure_message_names_no_path(self) -> None:
        """A coach-facing string must not carry a filesystem path or key."""
        bad = self.dir / "secret-name.mp4"
        bad.write_bytes(b"garbage")
        with self.assertRaises(media.MediaError) as caught:
            media.probe(str(bad))
        self.assertNotIn("secret-name", str(caught.exception))
        self.assertNotIn(str(self.dir), str(caught.exception))


@unittest.skipUnless(AVAILABLE, "pinned ffmpeg and ffprobe are not available")
class TranscodeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="shoulder-media-"))
        self.addCleanup(self._clean)
        self.kept: list[float | None] = []

    def _clean(self) -> None:
        for child in self.dir.glob("*"):
            child.unlink(missing_ok=True)
        self.dir.rmdir()

    def keep_going(self, progress: float | None = None) -> bool:
        self.kept.append(progress)
        return True

    def test_the_golden_clip_becomes_a_fast_start_720p_mp4(self) -> None:
        source = generate(self.dir / "golden.mp4", seconds=3, size="1920x1080")
        destination = self.dir / "coach-720p.mp4"
        media.transcode(
            str(source), str(destination), media.probe(str(source)), self.keep_going
        )

        self.assertTrue(destination.is_file())
        result = media.probe(str(destination))
        self.assertEqual((result.width, result.height), (1280, 720))

        streams = json.loads(
            subprocess.run(
                [
                    media._tool("ffprobe"),
                    "-v",
                    "quiet",
                    "-print_format",
                    "json",
                    "-show_streams",
                    "-show_format",
                    str(destination),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
            ).stdout
        )
        codecs = {s["codec_type"]: s["codec_name"] for s in streams["streams"]}
        self.assertEqual(codecs.get("video"), "h264")
        if "audio" in codecs:
            self.assertEqual(codecs["audio"], "aac")
        # ADR 0001: fast-start metadata, so the browser can play before the
        # whole object has arrived.
        self.assertIn("faststart", _moov_first(destination))

    def test_a_portrait_source_is_not_stretched(self) -> None:
        source = generate(self.dir / "portrait.mp4", seconds=2, size="480x854")
        destination = self.dir / "portrait-720p.mp4"
        media.transcode(
            str(source), str(destination), media.probe(str(source)), self.keep_going
        )
        result = media.probe(str(destination))
        self.assertLessEqual(max(result.width, result.height), media.TARGET_LONG_EDGE)
        self.assertAlmostEqual(result.width / result.height, 480 / 854, places=1)

    def test_a_silent_source_still_produces_playable_video(self) -> None:
        source = generate(self.dir / "quiet.mp4", seconds=2, audio=False)
        destination = self.dir / "quiet-720p.mp4"
        media.transcode(
            str(source), str(destination), media.probe(str(source)), self.keep_going
        )
        self.assertGreater(destination.stat().st_size, 0)

    def test_progress_is_reported_and_bounded(self) -> None:
        source = generate(self.dir / "progress.mp4", seconds=3)
        media.transcode(
            str(source),
            str(self.dir / "out.mp4"),
            media.probe(str(source)),
            self.keep_going,
        )
        seen = [value for value in self.kept if value is not None]
        for value in seen:
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)

    def test_a_refused_continuation_stops_the_encode(self) -> None:
        """Cancellation and shutdown both arrive as `keep_going()` going false."""
        source = generate(self.dir / "cancel.mp4", seconds=8, size="1280x720")
        calls = {"n": 0}

        def stop(progress: float | None = None) -> bool:
            calls["n"] += 1
            return calls["n"] < 2

        with self.assertRaises(Exception):
            media.transcode(
                str(source),
                str(self.dir / "cancelled.mp4"),
                media.probe(str(source)),
                stop,
            )

    def test_transcoding_a_corrupt_source_fails_safely(self) -> None:
        bad = self.dir / "bad.mp4"
        bad.write_bytes(b"still not a video" * 200)
        with self.assertRaises(media.MediaError):
            media.probe(str(bad))


@unittest.skipUnless(AVAILABLE, "pinned ffmpeg and ffprobe are not available")
class SpriteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="shoulder-sprite-"))
        self.addCleanup(self._clean)

    def _clean(self) -> None:
        for child in self.dir.rglob("*"):
            if child.is_file():
                child.unlink(missing_ok=True)
        for child in sorted(self.dir.rglob("*"), reverse=True):
            if child.is_dir():
                child.rmdir()
        self.dir.rmdir()

    def test_a_clip_produces_the_sheets_its_geometry_predicts(self) -> None:
        source = generate(self.dir / "sprite.mp4", seconds=6, size="640x360")
        layout = timeline.sprite_layout(media.probe(str(source)).duration_ms)
        sheets = media.sprite_sheets(str(source), str(self.dir), layout)
        self.assertEqual(len(sheets), layout.sheet_count)
        for sheet in sheets:
            self.assertTrue(Path(sheet).is_file())
            self.assertGreater(Path(sheet).stat().st_size, 0)

    def test_the_index_describes_the_same_geometry(self) -> None:
        layout = timeline.sprite_layout(90 * 60 * 1000)
        document = media.index_document(layout, layout.sheet_count)
        self.assertEqual(document["interval_ms"], layout.interval_ms)
        self.assertEqual(document["tile_count"], layout.tile_count)
        self.assertEqual(document["columns"], layout.columns)
        self.assertEqual(document["rows"], layout.rows)


def _moov_first(path: Path) -> str:
    """Report whether `moov` precedes `mdat`, which is what fast start means."""
    head = path.read_bytes()[:6_000_000]
    moov = head.find(b"moov")
    mdat = head.find(b"mdat")
    if moov == -1:
        return "no-moov"
    if mdat == -1 or moov < mdat:
        return "faststart"
    return "moov-after-mdat"


if __name__ == "__main__":  # pragma: no cover - convenience
    unittest.main()
