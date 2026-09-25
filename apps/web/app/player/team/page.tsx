import type { components } from "@shoulder/contracts";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { requirePlayerSession } from "../session";
import { km, kmh } from "../sessions/format";
import { read } from "../sessions/server";
import {
  backLink,
  errorBox,
  focus,
  pageTitle,
  panel,
  sectionTitle,
} from "../ui";
import { LeaveBoard, NicknameForm } from "./membership";

type Schema = components["schemas"];
type Metric = Schema["Leaderboard"]["metric"];
type Period = Schema["Leaderboard"]["period"];

const metrics: [Metric, string, (value: number) => string][] = [
  ["distance", "Distance", km],
  ["sprints", "Sprints", (n) => `${n} ${n === 1 ? "sprint" : "sprints"}`],
  ["top_speed", "Top speed", kmh],
  ["sessions", "Sessions", (n) => `${n} ${n === 1 ? "session" : "sessions"}`],
];
const periods: [Period, string][] = [
  ["week", "This week"],
  ["season", "Season"],
];

const chipBase = `inline-flex min-h-11 items-center rounded-full border px-4 text-[15px] font-semibold transition-colors duration-150 ease-out ${focus}`;
const chipOn = "border-ink bg-ink text-paper";
const chipOff =
  "border-control-border text-ink-2 hover:bg-surface-subtle hover:text-ink";

function pick<T extends string>(value: string | undefined, allowed: T[]): T {
  return allowed.find((item) => item === value) ?? allowed[0];
}

export default async function TeamPage({
  searchParams,
}: {
  searchParams: Promise<{ metric?: string; period?: string }>;
}) {
  const { token } = await requirePlayerSession("/player/team");
  const query = await searchParams;
  const metric = pick(
    query.metric,
    metrics.map(([key]) => key),
  );
  const period = pick(
    query.period,
    periods.map(([key]) => key),
  );
  const membership = await read<Schema["LeaderboardMembership"]>(
    token,
    "/v1/player/leaderboard-membership",
  );
  const board = membership.data
    ? await read<Schema["Leaderboard"]>(
        token,
        `/v1/teams/${encodeURIComponent(membership.data.team_id)}/leaderboard?metric=${metric}&period=${period}`,
      )
    : null;
  const nickname = membership.data?.nickname ?? null;
  const format = metrics.find(([key]) => key === metric)?.[2] ?? String;
  const href = (m: Metric, p: Period) => `/player/team?metric=${m}&period=${p}`;

  return (
    <div className="max-w-[760px]">
      <Link href="/player/sessions" className={backLink}>
        <ArrowLeft size={18} strokeWidth={2} aria-hidden="true" />
        Sessions
      </Link>
      <h1 className={`${pageTitle} mt-2`}>Team board</h1>
      <p className="mt-3 max-w-[60ch] text-[16px] leading-6 text-ink-2">
        Tracking totals side by side, only for players who join.
      </p>

      {membership.data === null ? (
        <p role="alert" className={`${errorBox} mt-8`}>
          The team board could not be loaded. Try again in a moment.
        </p>
      ) : (
        <>
          <section
            aria-labelledby="membership-title"
            className={`${panel} mt-8 p-5 md:p-6`}
          >
            <h2 id="membership-title" className={sectionTitle}>
              {nickname
                ? `You're on the board as ${nickname}`
                : "Join the board"}
            </h2>
            <ul className="mt-3 space-y-2 text-[16px] leading-6 text-ink-2">
              <li className="border-l-2 border-line-strong pl-4">
                Shared: your session totals for distance, sprints, top speed and
                number of sessions. Never your location, heatmap or notes.
              </li>
              <li className="border-l-2 border-line-strong pl-4">
                Shown under a nickname you choose, never your real name.
              </li>
              <li className="border-l-2 border-line-strong pl-4">
                Only your teammates and your coach can see it.
              </li>
              <li className="border-l-2 border-line-strong pl-4">
                Leave any time and you disappear from it straight away.
              </li>
            </ul>
            <div className="mt-5">
              <NicknameForm key={nickname ?? ""} current={nickname} />
            </div>
            {nickname ? (
              <div className="mt-4">
                <LeaveBoard />
              </div>
            ) : null}
          </section>

          <section aria-labelledby="board-title" className="mt-10">
            <h2 id="board-title" className={sectionTitle}>
              {periods.find(([key]) => key === period)?.[1]}
            </h2>
            <nav aria-label="Time period" className="mt-4">
              <ul className="flex flex-wrap gap-2">
                {periods.map(([key, label]) => (
                  <li key={key}>
                    <Link
                      href={href(metric, key)}
                      scroll={false}
                      aria-current={key === period ? "true" : undefined}
                      className={`${chipBase} ${key === period ? chipOn : chipOff}`}
                    >
                      {label}
                    </Link>
                  </li>
                ))}
              </ul>
            </nav>
            <nav aria-label="What to show" className="mt-3">
              <ul className="flex flex-wrap gap-2">
                {metrics.map(([key, label]) => (
                  <li key={key}>
                    <Link
                      href={href(key, period)}
                      scroll={false}
                      aria-current={key === metric ? "true" : undefined}
                      className={`${chipBase} ${key === metric ? chipOn : chipOff}`}
                    >
                      {label}
                    </Link>
                  </li>
                ))}
              </ul>
            </nav>

            {board?.data == null ? (
              <p role="alert" className={`${errorBox} mt-6`}>
                The board could not be loaded. Try again in a moment.
              </p>
            ) : board.data.entries.length < 2 ? (
              <div className="mt-6 rounded-xl border border-dashed border-control-border px-5 py-8 md:px-8">
                <p className="text-[16px] font-semibold">
                  The board appears once two teammates have joined.
                </p>
                <p className="mt-1 text-[16px] leading-6 text-ink-2">
                  Joining is up to each player.
                </p>
              </div>
            ) : (
              <ol className="mt-6 divide-y divide-line border-y border-line">
                {board.data.entries.map((entry) => (
                  <li
                    key={`${entry.nickname}-${entry.value}-${entry.is_me}`}
                    className={`flex min-h-14 items-center justify-between gap-4 px-2 py-2 ${
                      entry.is_me ? "rounded-lg bg-surface-subtle" : ""
                    }`}
                  >
                    <span className="min-w-0 truncate text-[16px] font-semibold">
                      {entry.nickname}
                      {entry.is_me ? (
                        <span className="ml-2 inline-flex min-h-6 items-center rounded-full bg-ink px-2 text-[13px] font-semibold text-paper">
                          You
                        </span>
                      ) : null}
                    </span>
                    <span className="shrink-0 text-[16px] tabular-nums text-ink-2">
                      {format(entry.value)}
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </>
      )}
    </div>
  );
}
