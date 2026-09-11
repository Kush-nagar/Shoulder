/**
 * Sprite timeline geometry, in TypeScript.
 *
 * This is the same function as `services/timeline.py`. The worker renders the
 * sheets, the API describes them, and the browser looks tiles up in them; if
 * any of the three disagreed about where a timestamp lands, the scrubber would
 * show the wrong frame. `tests/timeline.test.mjs` and `tests/test_media.py`
 * assert the two implementations agree on the same table of durations.
 *
 * Pure arithmetic, no React and no I/O.
 */

export const TILE_WIDTH = 160;
export const TILE_HEIGHT = 90;
export const COLUMNS = 10;
export const ROWS = 10;
export const TILES_PER_SHEET = COLUMNS * ROWS;
/** Four objects for a whole match, not hundreds of images. */
export const MAX_SHEETS = 4;
export const MAX_TILES = TILES_PER_SHEET * MAX_SHEETS;
export const MIN_INTERVAL_MS = 2000;

export type SpriteLayout = {
  interval_ms: number;
  tile_count: number;
  sheet_count: number;
  tile_width: number;
  tile_height: number;
  columns: number;
  rows: number;
};

/** At most four sheets of a hundred tiles, never finer than two seconds. */
export function spriteLayout(durationMs: number): SpriteLayout {
  if (durationMs <= 0) throw new Error("duration must be positive");
  let tiles = Math.min(
    MAX_TILES,
    Math.max(1, Math.ceil(durationMs / MIN_INTERVAL_MS)),
  );
  const interval = Math.max(MIN_INTERVAL_MS, Math.ceil(durationMs / tiles));
  tiles = Math.min(MAX_TILES, Math.max(1, Math.ceil(durationMs / interval)));
  return {
    interval_ms: interval,
    tile_count: tiles,
    sheet_count: Math.ceil(tiles / TILES_PER_SHEET),
    tile_width: TILE_WIDTH,
    tile_height: TILE_HEIGHT,
    columns: COLUMNS,
    rows: ROWS,
  };
}

/** Which sheet, column, and row hold the tile for a timestamp. */
export function spritePosition(
  timeMs: number,
  layout: SpriteLayout,
): { sheet: number; column: number; row: number } {
  const index = Math.min(
    layout.tile_count - 1,
    Math.max(0, Math.floor(timeMs / layout.interval_ms)),
  );
  const within = index % TILES_PER_SHEET;
  return {
    sheet: Math.floor(index / TILES_PER_SHEET),
    column: within % layout.columns,
    row: Math.floor(within / layout.columns),
  };
}

/**
 * CSS `background-position` for a tile, in pixels.
 *
 * Negative offsets, because the sheet is the background and the tile-sized
 * element is the window onto it.
 */
export function tileOffset(
  timeMs: number,
  layout: SpriteLayout,
): { sheet: number; x: number; y: number } {
  const { sheet, column, row } = spritePosition(timeMs, layout);
  // `|| 0` normalises the first row and column: `-0 * n` is `-0`, which is a
  // different value from `0` to anything comparing strictly.
  return {
    sheet,
    x: -(column * layout.tile_width) || 0,
    y: -(row * layout.tile_height) || 0,
  };
}

/** `h:mm:ss` for a match clock, or `m:ss` under an hour. */
export function formatClock(timeMs: number): string {
  const total = Math.max(0, Math.floor(timeMs / 1000));
  const seconds = total % 60;
  const minutes = Math.floor(total / 60) % 60;
  const hours = Math.floor(total / 3600);
  const pad = (value: number) => String(value).padStart(2, "0");
  return hours > 0
    ? `${hours}:${pad(minutes)}:${pad(seconds)}`
    : `${minutes}:${pad(seconds)}`;
}
