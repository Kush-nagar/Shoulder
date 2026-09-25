/**
 * Live GPS tracking (ADR 0023). Fixes live in this closure only: they are
 * never stored, logged, or sent. `stop()` returns aggregates alone.
 */
import {
  type Fix,
  haversine,
  median,
  type SessionSummary,
  summarise,
  usable,
} from "./metrics";

export type TrackingStatus =
  | "waiting" // no usable fix yet
  | "tracking"
  | "poor" // recent fixes too inaccurate, or none for a while
  | "denied"
  | "unavailable";

export type LiveStats = {
  status: TrackingStatus;
  elapsedS: number;
  distanceM: number;
  speedKmh: number;
  halfTimeMarked: boolean;
};

export type Tracker = {
  stop(): SessionSummary;
  markHalfTime(): void;
};

const STALE_MS = 15_000;

type WakeLockLike = { release(): Promise<void> };

export function startTracking(onUpdate: (live: LiveStats) => void): Tracker {
  const startedAt = Date.now();
  const fixes: Fix[] = [];
  const recent: number[] = [];
  let distance = 0;
  let lastFixAt = 0;
  let lastAccuracy = Number.POSITIVE_INFINITY;
  let halfAt: number | null = null;
  let status: TrackingStatus = "waiting";
  let wakeLock: WakeLockLike | null = null;
  let stopped = false;

  const emit = () => {
    const now = Date.now();
    if (
      (status === "tracking" || status === "poor") &&
      (now - lastFixAt > STALE_MS || lastAccuracy > 25)
    )
      status = "poor";
    else if (status === "poor") status = "tracking";
    onUpdate({
      status,
      elapsedS: Math.floor((now - startedAt) / 1000),
      distanceM: distance,
      speedKmh: now - lastFixAt > STALE_MS ? 0 : median(recent) * 3.6,
      halfTimeMarked: halfAt !== null,
    });
  };

  const onFix = (position: GeolocationPosition) => {
    const fix: Fix = {
      lat: position.coords.latitude,
      lon: position.coords.longitude,
      t: position.timestamp || Date.now(),
      accuracy: position.coords.accuracy,
    };
    lastAccuracy = fix.accuracy;
    if (!usable(fix)) {
      if (status === "tracking") status = "poor";
      emit();
      return;
    }
    const previous = fixes.at(-1);
    if (previous && fix.t > previous.t) {
      const step = haversine(previous, fix);
      const speed = step / ((fix.t - previous.t) / 1000);
      if (speed <= 12.5) {
        distance += step;
        recent.push(speed);
        if (recent.length > 3) recent.shift();
      }
    }
    if (!previous || fix.t > previous.t) fixes.push(fix);
    lastFixAt = Date.now();
    status = "tracking";
    emit();
  };

  const onError = (error: GeolocationPositionError) => {
    status = error.code === error.PERMISSION_DENIED ? "denied" : "poor";
    emit();
  };

  const geo = typeof navigator !== "undefined" ? navigator.geolocation : null;
  const watchId = geo
    ? geo.watchPosition(onFix, onError, {
        enableHighAccuracy: true,
        maximumAge: 0,
        timeout: 20_000,
      })
    : null;
  if (!geo) status = "unavailable";

  // Keeps the screen on so the browser keeps receiving fixes. Optional: a
  // browser without it tracks until the phone sleeps.
  const lockScreen = async () => {
    try {
      const api = (
        navigator as Navigator & {
          wakeLock?: { request(type: "screen"): Promise<WakeLockLike> };
        }
      ).wakeLock;
      if (api && !stopped) wakeLock = await api.request("screen");
    } catch {
      wakeLock = null;
    }
  };
  const onVisible = () => {
    if (document.visibilityState === "visible") void lockScreen();
  };
  void lockScreen();
  document.addEventListener("visibilitychange", onVisible);
  const timer = setInterval(emit, 1000);
  emit();

  return {
    markHalfTime() {
      if (halfAt === null && !stopped) {
        halfAt = Date.now();
        emit();
      }
    },
    stop() {
      stopped = true;
      clearInterval(timer);
      if (geo && watchId !== null) geo.clearWatch(watchId);
      document.removeEventListener("visibilitychange", onVisible);
      void wakeLock?.release().catch(() => undefined);
      const summary = summarise(fixes, startedAt, Date.now(), halfAt);
      fixes.length = 0;
      return summary;
    },
  };
}
