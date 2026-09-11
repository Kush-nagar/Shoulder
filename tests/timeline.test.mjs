import assert from "node:assert/strict";
import test from "node:test";
import {
  formatClock,
  MAX_SHEETS,
  MAX_TILES,
  MIN_INTERVAL_MS,
  spriteLayout,
  spritePosition,
  tileOffset,
} from "../apps/web/lib/timeline.ts";

/**
 * The durations `tests/test_media.py` also checks. If these two files ever
 * disagree, the scrubber shows a frame from the wrong moment.
 */
const SHARED_DURATIONS = [
  1,
  1000,
  40_000,
  5 * 60_000,
  90 * 60_000,
  4 * 3_600_000,
];

test("a full match stays within four sheets", () => {
  const layout = spriteLayout(90 * 60 * 1000);
  assert.ok(layout.sheet_count <= MAX_SHEETS);
  assert.ok(layout.tile_count <= MAX_TILES);
  assert.ok(layout.interval_ms >= MIN_INTERVAL_MS);
});

test("a short clip is never finer than two seconds", () => {
  const layout = spriteLayout(40 * 1000);
  assert.equal(layout.interval_ms, MIN_INTERVAL_MS);
  assert.equal(layout.sheet_count, 1);
});

test("geometry is deterministic across the shared durations", () => {
  for (const duration of SHARED_DURATIONS) {
    assert.deepEqual(spriteLayout(duration), spriteLayout(duration));
  }
});

test("a non-positive duration is refused", () => {
  for (const duration of [0, -1]) {
    assert.throws(() => spriteLayout(duration), /positive/);
  }
});

test("every tile lands on a real sheet", () => {
  const duration = 90 * 60 * 1000;
  const layout = spriteLayout(duration);
  for (const at of [0, 1, duration / 2, duration - 1, duration, duration * 2]) {
    const { sheet, column, row } = spritePosition(at, layout);
    assert.ok(sheet >= 0 && sheet < layout.sheet_count);
    assert.ok(column >= 0 && column < layout.columns);
    assert.ok(row >= 0 && row < layout.rows);
  }
});

test("a timestamp past the end clamps rather than overflowing", () => {
  const layout = spriteLayout(60_000);
  assert.deepEqual(spritePosition(1e9, layout), spritePosition(60_000, layout));
});

test("tile offsets are negative multiples of the tile size", () => {
  const layout = spriteLayout(5 * 60_000);
  const { x, y } = tileOffset(3 * 60_000, layout);
  assert.ok(x <= 0 && y <= 0);
  // `Math.abs`, because a negative dividend yields `-0`, which is numerically
  // zero but not strictly equal to it.
  assert.equal(Math.abs(x % layout.tile_width), 0);
  assert.equal(Math.abs(y % layout.tile_height), 0);
});

test("the first tile offsets to a plain zero, not negative zero", () => {
  const layout = spriteLayout(5 * 60_000);
  assert.deepEqual(tileOffset(0, layout), { sheet: 0, x: 0, y: 0 });
  assert.ok(Object.is(tileOffset(0, layout).x, 0));
});

test("the match clock reads plainly on both sides of an hour", () => {
  assert.equal(formatClock(0), "0:00");
  assert.equal(formatClock(9_000), "0:09");
  assert.equal(formatClock(65_000), "1:05");
  assert.equal(formatClock(59 * 60_000 + 59_000), "59:59");
  assert.equal(formatClock(60 * 60_000), "1:00:00");
  assert.equal(formatClock(90 * 60_000 + 5_000), "1:30:05");
});

test("a negative clock reads as zero rather than as a minus sign", () => {
  assert.equal(formatClock(-1), "0:00");
});
