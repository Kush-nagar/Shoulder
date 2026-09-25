import type { SessionSummary } from "./server";
import { km, minutes, weekLabel } from "./format";

/**
 * Where the player spent time: 96 cells over a pitch drawing. The grid runs
 * along the track's own longest direction, so it has no compass or location.
 */
export function Heatmap({ cells, label }: { cells: number[]; label: string }) {
  return (
    <figure className="min-w-0">
      <div
        role="img"
        aria-label={`${label}: where you spent time, shown on a 12 by 8 grid.`}
        className="relative aspect-[3/2] w-full overflow-hidden rounded-[14px] border border-night-line bg-night"
      >
        <div className="absolute inset-0 grid grid-cols-12 grid-rows-8">
          {cells.map((value, index) => (
            <span
              // biome-ignore lint/suspicious/noArrayIndexKey: fixed 96-cell grid
              key={index}
              className="bg-action"
              style={{ opacity: value ? 0.12 + (value / 1000) * 0.78 : 0 }}
            />
          ))}
        </div>
        <svg
          viewBox="0 0 120 80"
          aria-hidden="true"
          className="absolute inset-0 size-full text-night-muted opacity-50"
          fill="none"
          stroke="currentColor"
          strokeWidth="0.6"
        >
          <rect x="2" y="2" width="116" height="76" />
          <line x1="60" y1="2" x2="60" y2="78" />
          <circle cx="60" cy="40" r="9" />
          <rect x="2" y="22" width="16" height="36" />
          <rect x="102" y="22" width="16" height="36" />
        </svg>
      </div>
      <figcaption className="mt-2 text-[13px] leading-[1.4] text-muted">
        {label}. Drawn along the longest direction you moved; it doesn&apos;t
        know which end was which.
      </figcaption>
    </figure>
  );
}

/** Twelve weekly distance bars in plain CSS. Zero weeks show a baseline. */
export function WeeklyChart({ weeks }: { weeks: SessionSummary["weeks"] }) {
  const peak = Math.max(1, ...weeks.map((week) => week.distance_m));
  return (
    <figure>
      <ol
        aria-label="Distance each week"
        className="flex h-40 items-end gap-1 border-b border-line-strong md:h-48 md:gap-2"
      >
        {weeks.map((week) => (
          <li
            key={week.week_start}
            className="flex h-full min-w-0 flex-1 flex-col justify-end"
          >
            <span className="sr-only">
              Week of {weekLabel(week.week_start)}: {km(week.distance_m)},{" "}
              {week.sessions} {week.sessions === 1 ? "session" : "sessions"},{" "}
              {minutes(week.duration_s)}
            </span>
            <span
              aria-hidden="true"
              className="block rounded-t-[4px] bg-action"
              style={{
                height: `${(week.distance_m / peak) * 100}%`,
                minHeight: week.distance_m ? 3 : 0,
              }}
            />
          </li>
        ))}
      </ol>
      <div
        aria-hidden="true"
        className="mt-2 flex justify-between text-[13px] text-muted tabular-nums"
      >
        <span>{weeks[0] ? weekLabel(weeks[0].week_start) : ""}</span>
        <span>This week</span>
      </div>
      <figcaption className="mt-1 text-[13px] text-muted">
        Distance per week, last {weeks.length} weeks. Tallest bar{" "}
        {km(Math.max(0, ...weeks.map((week) => week.distance_m)))}.
      </figcaption>
    </figure>
  );
}
