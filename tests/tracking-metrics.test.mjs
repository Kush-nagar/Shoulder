import assert from "node:assert/strict";
import test from "node:test";
import {
  countSprints,
  gpsQuality,
  haversine,
  heatmap,
  median,
  pitchFrame,
  segments,
  smoothedSpeeds,
  summarise,
} from "../apps/web/app/player/sessions/tracking/metrics.ts";

// One degree of latitude is ~111,195 m on the haversine sphere.
const M_PER_DEG = 111_195;
const north = (metres, t, accuracy = 5) => ({
  lat: 51.5 + metres / M_PER_DEG,
  lon: -0.12,
  t,
  accuracy,
});

test("haversine measures a known distance", () => {
  const d = haversine(north(0, 0), north(100, 0));
  assert.ok(Math.abs(d - 100) < 0.5, `got ${d}`);
});

test("median handles odd, even and empty input", () => {
  assert.equal(median([3, 1, 2]), 2);
  assert.equal(median([4, 1, 2, 3]), 2.5);
  assert.equal(median([]), 0);
});

test("a single-fix spike is removed by the 3-sample median", () => {
  // 5 m/s steady, one 11 m/s spike (below the glitch cap).
  const steps = [5, 5, 11, 5, 5];
  let at = 0;
  const fixes = [north(0, 0)];
  steps.forEach((step, i) => {
    at += step;
    fixes.push(north(at, (i + 1) * 1000));
  });
  const speeds = smoothedSpeeds(segments(fixes));
  assert.ok(Math.max(...speeds) < 5.1, `got ${speeds}`);
});

test("GPS jumps count for neither distance nor speed", () => {
  const fixes = [
    north(0, 0),
    north(5, 1000),
    north(505, 2000),
    north(510, 3000),
  ];
  assert.equal(segments(fixes).length, 2);
});

test("a sprint is above 25 km/h for at least one second", () => {
  const seg = (dt, speed) => ({ t: 0, dt, distance: speed * dt, speed });
  const fast = 8; // 28.8 km/h
  const slow = 3;
  const segs = [
    seg(1, slow),
    seg(0.5, fast),
    seg(1, slow), // 0.5 s burst: not a sprint
    seg(1, fast),
    seg(1, fast),
    seg(1, slow), // one sprint
    seg(1, fast),
    seg(1, slow), // another
  ];
  assert.equal(
    countSprints(
      segs,
      segs.map((s) => s.speed),
    ),
    2,
  );
});

test("gps quality follows the typical accuracy", () => {
  assert.equal(gpsQuality(new Array(40).fill(5)), "good");
  assert.equal(gpsQuality(new Array(40).fill(12)), "fair");
  assert.equal(gpsQuality(new Array(40).fill(20)), "poor");
  assert.equal(gpsQuality([3, 3]), "poor"); // too few fixes to trust
});

test("heatmap puts the long axis along 12 columns and peaks at 1000", () => {
  // A diagonal 100 m line: PCA rotates it onto the columns.
  const fixes = Array.from({ length: 120 }, (_, i) => ({
    lat: 51.5 + (i * 0.6) / M_PER_DEG,
    lon: -0.12 + (i * 0.6) / (M_PER_DEG * Math.cos((51.5 * Math.PI) / 180)),
    t: i * 1000,
    accuracy: 5,
  }));
  const grid = heatmap(fixes, pitchFrame(fixes));
  assert.equal(grid.length, 96);
  assert.equal(Math.max(...grid), 1000);
  assert.ok(grid.every((v) => Number.isInteger(v) && v >= 0 && v <= 1000));
  const usedCols = new Set();
  const usedRows = new Set();
  grid.forEach((v, i) => {
    if (v) {
      usedCols.add(i % 12);
      usedRows.add(Math.floor(i / 12));
    }
  });
  assert.equal(usedCols.size, 12);
  assert.equal(usedRows.size, 1);
});

test("no fixes gives an empty grid", () => {
  assert.deepEqual(heatmap([], pitchFrame([])), new Array(96).fill(0));
});

test("summarise drops inaccurate fixes and keeps no coordinates", () => {
  const start = Date.parse("2026-09-20T10:00:00Z");
  const fixes = [];
  for (let i = 0; i <= 600; i++) {
    fixes.push(north(i * 3, start + i * 1000, i % 50 === 0 ? 40 : 5));
  }
  const half = start + 300_000;
  const out = summarise(fixes, start, start + 600_000, half);
  assert.equal(out.duration_s, 600);
  assert.equal(out.half_split_s, 300);
  assert.ok(Math.abs(out.distance_m - 1800) < 10, `got ${out.distance_m}`);
  assert.ok(Math.abs(out.top_speed_cms - 300) < 10, `got ${out.top_speed_cms}`);
  assert.equal(out.sprint_count, 0);
  assert.equal(out.gps_quality, "good");
  assert.equal(out.heatmap.length, 96);
  assert.equal(out.heatmap_second_half.length, 96);
  const text = JSON.stringify(out);
  assert.ok(!text.includes("51.5") && !/lat|lon/.test(text));
});

test("summarise without half-time sends no second half", () => {
  const start = 0;
  const out = summarise([north(0, 0), north(3, 1000)], start, 120_000, null);
  assert.equal(out.half_split_s, null);
  assert.equal(out.heatmap_second_half, null);
  assert.equal(out.gps_quality, "poor");
});
