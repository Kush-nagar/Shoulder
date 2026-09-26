"use client";

import type { Timeline } from "../../../../lib/api";
import { formatClock } from "../../../../lib/timeline";

export type Marker = {
  id: string;
  startMs: number;
  endMs: number | null;
  selected: boolean;
};

/** A readable ruler step for the match length: about six to twelve labels. */
function rulerStep(durationMs: number): number {
  const minutes = durationMs / 60_000;
  if (minutes <= 1) return 10_000;
  if (minutes <= 3) return 30_000;
  if (minutes <= 12) return 60_000;
  if (minutes <= 30) return 5 * 60_000;
  if (minutes <= 75) return 10 * 60_000;
  return 15 * 60_000;
}

const pct = (value: number, total: number) =>
  `${Math.max(0, Math.min(100, (value / total) * 100))}%`;

/**
 * The match timeline (ADR 0026): a mono ruler, the coach's marked clips as
 * ranges on the track, the in point while a clip is open, and a lime
 * playhead. A native range input sits on top, so seeking stays precise and
 * keyboard/assistive-tech operable; everything drawn is decoration.
 */
export function MatchTimeline({
  durationMs,
  currentMs,
  hover,
  onHover,
  onSeek,
  markers,
  inMs,
  timeline,
  preview,
}: {
  durationMs: number;
  currentMs: number;
  hover: number | null;
  onHover: (ms: number | null) => void;
  onSeek: (ms: number) => void;
  markers: Marker[];
  inMs: number | null;
  timeline: Timeline | null;
  preview: { url: string; x: number; y: number } | null;
}) {
  const step = durationMs > 0 ? rulerStep(durationMs) : 0;
  const ticks =
    step > 0
      ? Array.from(
          { length: Math.floor(durationMs / step) + 1 },
          (_, index) => index * step,
        )
      : [];
  const total = Math.max(1, durationMs);
  return (
    <div className="relative px-3 pt-1 pb-3 md:px-4">
      <div aria-hidden="true" className="relative h-4">
        {ticks.map((at) => (
          <span
            key={at}
            className={`absolute top-0 font-mono text-[10px] leading-4 text-night-muted ${
              at / total > 0.96 ? "-translate-x-full pr-1" : "pl-1"
            }`}
            style={{ left: pct(at, total) }}
          >
            {formatClock(at)}
          </span>
        ))}
      </div>
      <div className="group/track relative h-9 rounded-md has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-action-on-night">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0"
        >
          {ticks.map((at) => (
            <span
              key={at}
              className="absolute -top-4 h-5 w-px bg-night-line"
              style={{ left: pct(at, total) }}
            />
          ))}
          {/* Track and the part already watched. */}
          <span className="absolute inset-x-0 top-3.5 h-2 rounded-sm bg-on-night/8" />
          <span
            className="absolute top-3.5 left-0 h-2 rounded-l-sm bg-on-night/14"
            style={{ width: pct(currentMs, total) }}
          />
          {markers.map((marker) => (
            <span
              key={marker.id}
              className={`absolute top-2.5 h-4 min-w-0.5 rounded-[2px] border-l-2 transition-colors duration-140 ${
                marker.selected
                  ? "border-action-on-night bg-action-on-night/35"
                  : "border-night-muted bg-night-muted/35 group-hover/track:bg-night-muted/50"
              }`}
              style={{
                left: pct(marker.startMs, total),
                width: pct(
                  (marker.endMs ?? marker.startMs) - marker.startMs,
                  total,
                ),
              }}
            />
          ))}
          {inMs !== null ? (
            <span
              className="absolute top-1 bottom-1 w-0.5 rounded-full bg-action-on-night/70"
              style={{ left: pct(inMs, total) }}
            />
          ) : null}
          {hover !== null ? (
            <span
              className="absolute top-0 bottom-0 w-px bg-on-night/35"
              style={{ left: pct(hover, total) }}
            />
          ) : null}
          {/* Playhead: the one lime line on the stage. */}
          <span
            className="absolute -top-1 bottom-0 w-0.5 -translate-x-1/2 bg-action-on-night"
            style={{ left: pct(currentMs, total) }}
          >
            <span className="absolute -top-0.5 left-1/2 size-2 -translate-x-1/2 rotate-45 rounded-[1px] bg-action-on-night" />
          </span>
        </div>
        <label htmlFor="scrubber" className="sr-only">
          Seek through the match
        </label>
        <input
          id="scrubber"
          type="range"
          min={0}
          max={Math.max(0, Math.round(durationMs))}
          step={100}
          value={Math.round(currentMs)}
          aria-valuetext={formatClock(currentMs)}
          onChange={(event) => onSeek(Number(event.target.value))}
          onMouseMove={(event) => {
            const box = event.currentTarget.getBoundingClientRect();
            const ratio = (event.clientX - box.left) / box.width;
            onHover(Math.max(0, Math.min(1, ratio)) * durationMs);
          }}
          onMouseLeave={() => onHover(null)}
          className="absolute inset-0 size-full cursor-pointer appearance-none opacity-0 outline-none"
        />
      </div>

      {hover !== null ? (
        <div
          className="pointer-events-none absolute bottom-full z-10 mb-2 flex -translate-x-1/2 flex-col items-center gap-1"
          style={{
            left: `clamp(${(timeline?.tile_width ?? 60) / 2 + 12}px, ${pct(hover, total)}, calc(100% - ${(timeline?.tile_width ?? 60) / 2 + 12}px))`,
          }}
        >
          {preview && timeline ? (
            <div
              aria-hidden="true"
              className="overflow-hidden rounded-md border border-line shadow-pop"
              style={{
                width: timeline.tile_width,
                height: timeline.tile_height,
                backgroundImage: `url(${preview.url})`,
                backgroundPosition: `${preview.x}px ${preview.y}px`,
              }}
            />
          ) : null}
          <span
            aria-hidden="true"
            className="rounded-sm bg-popover px-1.5 py-0.5 font-mono text-[11px] text-ink shadow-pop"
          >
            {formatClock(hover)}
          </span>
        </div>
      ) : null}
    </div>
  );
}
