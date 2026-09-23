// Pure pose math for the practice lane (ADR 0021). No DOM, no MediaPipe:
// per-frame landmarks go in, only the aggregate contract features come out.

// Temporary mirror of the contract; switch to generated OpenAPI types at integration.
export type Percentiles = { p10: number; p50: number; p90: number };
export type PracticeFeatures = {
  frames_analyzed: number;
  fps: number;
  duration_ms: number;
  knee_flexion_deg: Percentiles;
  hip_flexion_deg: Percentiles;
  trunk_lean_deg: Percentiles;
  head_turns: number;
  head_turns_per_min: number;
  stance_width_ratio: { p50: number };
  visibility_mean: number;
};

export type Point = { x: number; y: number; visibility?: number };

// BlazePose 33-landmark indices.
const NOSE = 0;
const SHOULDER = [11, 12];
const HIP = [23, 24];
const KNEE = [25, 26];
const ANKLE = [27, 28];
const USED = [NOSE, ...SHOULDER, ...HIP, ...KNEE, ...ANKLE];
const MIN_VIS = 0.5;
// Head yaw proxy hysteresis: a turn is |yaw| rising past TURN after
// having settled under CENTER. Proxy, not a head-orientation profile.
const TURN = 0.35;
const CENTER = 0.15;

const round1 = (n: number) => Math.round(n * 10) / 10;

/** Interior angle ABC in degrees. */
export function angle(a: Point, b: Point, c: Point): number {
  const ab = Math.atan2(a.y - b.y, a.x - b.x);
  const cb = Math.atan2(c.y - b.y, c.x - b.x);
  let deg = Math.abs(((ab - cb) * 180) / Math.PI);
  if (deg > 180) deg = 360 - deg;
  return deg;
}

/** Linear-interpolated percentile (q in 0..1); 0 for no samples. */
export function percentile(values: number[], q: number): number {
  if (values.length === 0) return 0;
  const s = [...values].sort((x, y) => x - y);
  const i = (s.length - 1) * q;
  const lo = Math.floor(i);
  const hi = Math.ceil(i);
  return s[lo] + (s[hi] - s[lo]) * (i - lo);
}

const summary = (v: number[]): Percentiles => ({
  p10: round1(percentile(v, 0.1)),
  p50: round1(percentile(v, 0.5)),
  p90: round1(percentile(v, 0.9)),
});

/** Count excursions of |yaw| past TURN, re-armed only after returning under CENTER. */
export function countTurns(yaws: number[]): number {
  let turns = 0;
  let armed = true;
  for (const y of yaws) {
    const a = Math.abs(y);
    if (armed && a > TURN) {
      turns++;
      armed = false;
    } else if (a < CENTER) armed = true;
  }
  return turns;
}

const mid = (a: Point, b: Point): Point => ({
  x: (a.x + b.x) / 2,
  y: (a.y + b.y) / 2,
});
const dist = (a: Point, b: Point) => Math.hypot(a.x - b.x, a.y - b.y);
const seen = (...ps: Point[]) =>
  ps.every((p) => (p.visibility ?? 1) >= MIN_VIS);

/**
 * Accumulates per-frame samples. `aspect` = width / height, so normalized x
 * and y share a scale. Call `add(null)` for a sampled frame with no pose.
 */
export function createAccumulator(aspect: number) {
  const knee: number[] = [];
  const hip: number[] = [];
  const trunk: number[] = [];
  const stance: number[] = [];
  const yaws: number[] = [];
  let visSum = 0;
  let frames = 0;

  return {
    add(raw: Point[] | null) {
      frames++;
      if (!raw || raw.length < 33) return;
      const p = raw.map((l) => ({ ...l, x: l.x * aspect }));
      visSum +=
        USED.reduce((s, i) => s + (p[i].visibility ?? 1), 0) / USED.length;
      for (const side of [0, 1]) {
        const [s, h, k, a] = [SHOULDER, HIP, KNEE, ANKLE].map(
          (j) => p[j[side]],
        );
        if (seen(h, k, a)) knee.push(180 - angle(h, k, a));
        if (seen(s, h, k)) hip.push(180 - angle(s, h, k));
      }
      const [ls, rs] = SHOULDER.map((i) => p[i]);
      const [lh, rh] = HIP.map((i) => p[i]);
      const [la, ra] = ANKLE.map((i) => p[i]);
      const shoulderW = dist(ls, rs);
      if (seen(ls, rs, lh, rh)) {
        const sm = mid(ls, rs);
        const hm = mid(lh, rh);
        // Lean from vertical; image y grows downward.
        trunk.push(
          (Math.atan2(Math.abs(sm.x - hm.x), hm.y - sm.y) * 180) / Math.PI,
        );
      }
      if (shoulderW > 0.02 && seen(ls, rs)) {
        if (seen(la, ra)) stance.push(dist(la, ra) / shoulderW);
        if (seen(p[NOSE])) yaws.push((p[NOSE].x - mid(ls, rs).x) / shoulderW);
      }
    },
    finish(durationMs: number, fps: number): PracticeFeatures {
      const turns = countTurns(yaws);
      const minutes = durationMs / 60000;
      return {
        frames_analyzed: frames,
        fps: round1(fps),
        duration_ms: Math.round(durationMs),
        knee_flexion_deg: summary(knee),
        hip_flexion_deg: summary(hip),
        trunk_lean_deg: summary(trunk),
        head_turns: turns,
        head_turns_per_min: minutes > 0 ? round1(turns / minutes) : 0,
        stance_width_ratio: {
          p50: Math.min(10, round1(percentile(stance, 0.5))),
        },
        visibility_mean:
          frames > 0 ? Math.round((visSum / frames) * 100) / 100 : 0,
      };
    },
  };
}
