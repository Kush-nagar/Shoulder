/** Plain number formatting for session stats; no judgement words. */

export function km(metres: number) {
  return `${(metres / 1000).toFixed(metres < 10_000 ? 2 : 1)} km`;
}

export function kmh(cms: number) {
  return `${(cms * 0.036).toFixed(1)} km/h`;
}

/** Stopwatch style: 4:05 or 1:02:03. */
export function stopwatch(seconds: number) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return h
    ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
    : `${m}:${String(s).padStart(2, "0")}`;
}

export function minutes(seconds: number) {
  const m = Math.round(seconds / 60);
  return m >= 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m} min`;
}

export function sessionDate(value: string) {
  return new Intl.DateTimeFormat("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
  }).format(new Date(value));
}

export function weekLabel(value: string) {
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  }).format(new Date(value));
}

export const kindLabel = { training: "Training", match: "Match" } as const;

export const qualityLabel = {
  good: "Strong GPS signal",
  fair: "Patchy GPS signal",
  poor: "Weak GPS signal, so these numbers may be off",
} as const;
