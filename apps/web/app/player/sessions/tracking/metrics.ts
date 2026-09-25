/**
 * Pure session maths (ADR 0023). Latitude and longitude enter here and never
 * leave: the output is distances, speeds, counts, and a 12x8 grid laid on the
 * track's own principal axes, so it carries no geographic reference.
 */
import type { components } from "@shoulder/contracts";

type Create = components["schemas"]["TrainingSessionCreate"];

/** What the browser sends; the player adds `kind` and an optional `note`. */
export type SessionSummary = Omit<Create, "kind" | "note">;

export type Fix = {
  lat: number;
  lon: number;
  /** Epoch milliseconds. */
  t: number;
  /** Metres, 68% radius as reported by the device. */
  accuracy: number;
};

export const MAX_ACCURACY_M = 25;
export const SPRINT_MS = 25 / 3.6; // 25 km/h in m/s
export const SPRINT_MIN_S = 1;
/** Faster than any footballer: a GPS jump, not a run. */
export const GLITCH_MS = 12.5;
export const COLS = 12;
export const ROWS = 8;

const EARTH_M = 6_371_000;
const rad = (degrees: number) => (degrees * Math.PI) / 180;

export function haversine(a: Fix, b: Fix): number {
  const dLat = rad(b.lat - a.lat);
  const dLon = rad(b.lon - a.lon);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_M * Math.asin(Math.min(1, Math.sqrt(h)));
}

export function median(values: number[]): number {
  if (!values.length) return 0;
  const sorted = [...values].sort((x, y) => x - y);
  const mid = sorted.length >> 1;
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

export function usable(fix: Fix): boolean {
  return (
    Number.isFinite(fix.lat) &&
    Number.isFinite(fix.lon) &&
    Number.isFinite(fix.accuracy) &&
    fix.accuracy <= MAX_ACCURACY_M
  );
}

export type Segment = {
  t: number;
  dt: number;
  distance: number;
  speed: number;
};

/** Successive-fix segments; glitch jumps count for neither distance nor speed. */
export function segments(fixes: Fix[]): Segment[] {
  const out: Segment[] = [];
  for (let i = 1; i < fixes.length; i++) {
    const dt = (fixes[i].t - fixes[i - 1].t) / 1000;
    if (dt <= 0) continue;
    const distance = haversine(fixes[i - 1], fixes[i]);
    const speed = distance / dt;
    if (speed > GLITCH_MS) continue;
    out.push({ t: fixes[i].t, dt, distance, speed });
  }
  return out;
}

/** Each segment speed replaced by the median of it and its two predecessors. */
export function smoothedSpeeds(segs: Segment[]): number[] {
  return segs.map((_, i) =>
    median(segs.slice(Math.max(0, i - 2), i + 1).map((s) => s.speed)),
  );
}

/** Runs above 25 km/h lasting at least one second. */
export function countSprints(segs: Segment[], speeds: number[]): number {
  let count = 0;
  let run = 0;
  let counted = false;
  for (let i = 0; i < segs.length; i++) {
    if (speeds[i] > SPRINT_MS) {
      run += segs[i].dt;
      if (!counted && run >= SPRINT_MIN_S) {
        count++;
        counted = true;
      }
    } else {
      run = 0;
      counted = false;
    }
  }
  return count;
}

export function gpsQuality(
  accuracies: number[],
): SessionSummary["gps_quality"] {
  if (accuracies.length < 30) return "poor";
  const typical = median(accuracies);
  if (typical <= 8) return "good";
  if (typical <= 15) return "fair";
  return "poor";
}

type Frame = {
  toGrid: (fix: Fix) => [number, number];
};

/**
 * Local metres around the centroid, rotated so the longest spread of the
 * track (its first principal axis) runs along the 12 columns.
 */
export function pitchFrame(fixes: Fix[]): Frame | null {
  if (fixes.length < 2) return null;
  const lat0 = fixes.reduce((sum, f) => sum + f.lat, 0) / fixes.length;
  const lon0 = fixes.reduce((sum, f) => sum + f.lon, 0) / fixes.length;
  const scale = Math.cos(rad(lat0));
  const local = (f: Fix): [number, number] => [
    rad(f.lon - lon0) * scale * EARTH_M,
    rad(f.lat - lat0) * EARTH_M,
  ];
  const points = fixes.map(local);
  let xx = 0;
  let yy = 0;
  let xy = 0;
  for (const [x, y] of points) {
    xx += x * x;
    yy += y * y;
    xy += x * y;
  }
  const theta = 0.5 * Math.atan2(2 * xy, xx - yy);
  const [c, s] = [Math.cos(theta), Math.sin(theta)];
  const rotate = ([x, y]: [number, number]): [number, number] => [
    x * c + y * s,
    -x * s + y * c,
  ];
  const rotated = points.map(rotate);
  const us = rotated.map((p) => p[0]);
  const vs = rotated.map((p) => p[1]);
  const [uMin, uMax] = [Math.min(...us), Math.max(...us)];
  const [vMin, vMax] = [Math.min(...vs), Math.max(...vs)];
  const cell = (value: number, min: number, max: number, n: number) =>
    max - min < 1e-6
      ? n >> 1
      : Math.min(n - 1, Math.floor(((value - min) / (max - min)) * n));
  return {
    toGrid: (fix) => {
      const [u, v] = rotate(local(fix));
      return [cell(u, uMin, uMax, COLS), cell(v, vMin, vMax, ROWS)];
    },
  };
}

/** Row-major 12x8 counts, scaled so the busiest cell is 1000. */
export function heatmap(fixes: Fix[], frame: Frame | null): number[] {
  const grid = new Array<number>(COLS * ROWS).fill(0);
  if (!frame) return grid;
  for (const fix of fixes) {
    const [col, row] = frame.toGrid(fix);
    grid[row * COLS + col]++;
  }
  const peak = Math.max(...grid);
  return peak ? grid.map((n) => Math.round((n / peak) * 1000)) : grid;
}

const clamp = (value: number, max: number) =>
  Math.max(0, Math.min(max, Math.round(value)));

/** Everything the API stores, from fixes that never leave this function. */
export function summarise(
  fixes: Fix[],
  startedAt: number,
  endedAt: number,
  halfAt: number | null,
): SessionSummary {
  const kept = fixes.filter(usable);
  const segs = segments(kept);
  const speeds = smoothedSpeeds(segs);
  const duration = Math.min(Math.floor((endedAt - startedAt) / 1000), 14400);
  const frame = pitchFrame(kept);
  const half =
    halfAt !== null && halfAt > startedAt && halfAt < endedAt
      ? Math.floor((halfAt - startedAt) / 1000)
      : null;
  const split = half !== null && half > 0 && half < duration;
  return {
    started_at: new Date(startedAt).toISOString(),
    ended_at: new Date(endedAt).toISOString(),
    duration_s: duration,
    distance_m: clamp(
      segs.reduce((sum, s) => sum + s.distance, 0),
      30000,
    ),
    top_speed_cms: clamp(Math.max(0, ...speeds) * 100, 1300),
    sprint_count: clamp(countSprints(segs, speeds), 500),
    half_split_s: split ? half : null,
    heatmap: heatmap(kept, frame),
    heatmap_second_half:
      split && halfAt !== null
        ? heatmap(
            kept.filter((f) => f.t >= halfAt),
            frame,
          )
        : null,
    gps_quality: gpsQuality(kept.map((f) => f.accuracy)),
  };
}
