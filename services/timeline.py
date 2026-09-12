"""Sprite timeline geometry, shared by the worker that renders it and the API
that describes it.

Pure arithmetic with no dependencies, deliberately: the worker, the API, and
the browser all have to agree on where a timestamp lands, and the only way to
guarantee that is for the answer to be a function of duration alone.

`apps/web/lib/timeline.ts` is the same function in TypeScript;
`tests/timeline.test.mjs` and `tests/test_media.py` assert they agree.
"""

import math
from dataclasses import dataclass

TILE_WIDTH = 160
TILE_HEIGHT = 90
COLUMNS = 10
ROWS = 10
TILES_PER_SHEET = COLUMNS * ROWS
# Four objects for a whole match, not hundreds of images.
MAX_SHEETS = 4
MAX_TILES = TILES_PER_SHEET * MAX_SHEETS
MIN_INTERVAL_MS = 2000


@dataclass(frozen=True)
class SpriteLayout:
    interval_ms: int
    tile_count: int
    sheet_count: int
    tile_width: int = TILE_WIDTH
    tile_height: int = TILE_HEIGHT
    columns: int = COLUMNS
    rows: int = ROWS


def sprite_layout(duration_ms: int) -> SpriteLayout:
    """At most four sheets of a hundred tiles, never finer than two seconds.

    A 90-minute match becomes 400 tiles about 13.5 seconds apart across four
    sheets; a 40-second clip becomes 20 tiles two seconds apart on one.
    """
    if duration_ms <= 0:
        raise ValueError("duration must be positive")
    tiles = min(MAX_TILES, max(1, math.ceil(duration_ms / MIN_INTERVAL_MS)))
    interval_ms = max(MIN_INTERVAL_MS, math.ceil(duration_ms / tiles))
    tiles = min(MAX_TILES, max(1, math.ceil(duration_ms / interval_ms)))
    return SpriteLayout(
        interval_ms=interval_ms,
        tile_count=tiles,
        sheet_count=math.ceil(tiles / TILES_PER_SHEET),
    )


def sprite_position(time_ms: int, layout: SpriteLayout) -> tuple[int, int, int]:
    """(sheet, column, row) for a timestamp, clamped to the timeline."""
    index = min(layout.tile_count - 1, max(0, time_ms // layout.interval_ms))
    within = index % TILES_PER_SHEET
    return index // TILES_PER_SHEET, within % layout.columns, within // layout.columns
