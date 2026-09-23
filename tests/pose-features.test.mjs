import assert from "node:assert/strict";
import test from "node:test";
import {
  angle,
  countTurns,
  createAccumulator,
  percentile,
} from "../apps/web/app/player/practice/pose/features.ts";

test("angle returns the interior angle in degrees", () => {
  const b = { x: 0, y: 0 };
  assert.equal(Math.round(angle({ x: 1, y: 0 }, b, { x: 0, y: 1 })), 90);
  assert.equal(Math.round(angle({ x: 0, y: -1 }, b, { x: 0, y: 1 })), 180);
  assert.equal(Math.round(angle({ x: 1, y: 0 }, b, { x: 1, y: 0 })), 0);
});

test("percentile interpolates and is 0 for no samples", () => {
  assert.equal(percentile([], 0.5), 0);
  assert.equal(percentile([30, 10, 20], 0.5), 20);
  assert.equal(percentile([0, 10], 0.1), 1);
  assert.equal(percentile([0, 10], 0.9), 9);
});

test("head turns need a return to center before counting again", () => {
  assert.equal(countTurns([0, 0.5, 0.6, 0.5, 0]), 1);
  assert.equal(countTurns([0, 0.5, 0.2, 0.5]), 1); // never re-centered
  assert.equal(countTurns([0, -0.5, 0, 0.5, 0.1, -0.4]), 3);
});

function standing(noseX = 0.5) {
  const p = Array.from({ length: 33 }, () => ({
    x: 0.5,
    y: 0.5,
    visibility: 1,
  }));
  p[0] = { x: noseX, y: 0.1, visibility: 1 };
  p[11] = { x: 0.4, y: 0.2, visibility: 1 };
  p[12] = { x: 0.6, y: 0.2, visibility: 1 };
  p[23] = { x: 0.45, y: 0.5, visibility: 1 };
  p[24] = { x: 0.55, y: 0.5, visibility: 1 };
  p[25] = { x: 0.45, y: 0.7, visibility: 1 };
  p[26] = { x: 0.55, y: 0.7, visibility: 1 };
  p[27] = { x: 0.4, y: 0.9, visibility: 1 };
  p[28] = { x: 0.6, y: 0.9, visibility: 1 };
  return p;
}

test("accumulator emits only the aggregate contract fields", () => {
  const acc = createAccumulator(1);
  acc.add(standing(0.5));
  acc.add(standing(0.6)); // yaw 0.5 -> one turn
  acc.add(standing(0.5));
  acc.add(null);
  const f = acc.finish(30000, 15);
  assert.deepEqual(Object.keys(f).sort(), [
    "duration_ms",
    "fps",
    "frames_analyzed",
    "head_turns",
    "head_turns_per_min",
    "hip_flexion_deg",
    "knee_flexion_deg",
    "stance_width_ratio",
    "trunk_lean_deg",
    "visibility_mean",
  ]);
  assert.equal(f.frames_analyzed, 4);
  assert.equal(f.head_turns, 1);
  assert.equal(f.head_turns_per_min, 2);
  assert.equal(f.trunk_lean_deg.p50, 0);
  assert.equal(f.stance_width_ratio.p50, 1);
  assert.equal(f.visibility_mean, 0.75);
  assert.ok(f.knee_flexion_deg.p50 > 0 && f.knee_flexion_deg.p50 < 30);
  assert.ok(JSON.stringify(f).length < 4096);
});

test("low-visibility joints are skipped", () => {
  const acc = createAccumulator(1);
  const p = standing();
  for (const i of [23, 24, 25, 26, 27, 28]) p[i].visibility = 0.1;
  acc.add(p);
  const f = acc.finish(1000, 15);
  assert.deepEqual(f.knee_flexion_deg, { p10: 0, p50: 0, p90: 0 });
  assert.deepEqual(f.hip_flexion_deg, { p10: 0, p50: 0, p90: 0 });
});
