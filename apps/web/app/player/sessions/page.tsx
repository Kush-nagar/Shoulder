import { ChevronRight, Timer, Users } from "lucide-react";
import Link from "next/link";
import { requirePlayerSession } from "../session";
import {
  errorBox,
  focus,
  pageTitle,
  primaryButton,
  sectionTitle,
  textLink,
} from "../ui";
import { WeeklyChart } from "./charts";
import { km, kmh, kindLabel, minutes, sessionDate, stopwatch } from "./format";
import {
  fetchSessionSummary,
  fetchSessions,
  type SessionSummary,
} from "./server";

function Records({ records }: { records: SessionSummary["records"] }) {
  const rows = [
    ["Longest distance", records.distance_m, km],
    ["Top speed", records.top_speed_cms, kmh],
    ["Most sprints", records.sprint_count, String],
    ["Longest session", records.duration_s, minutes],
  ] as const;
  const shown = rows.filter(([, record]) => record);
  if (!shown.length) return null;
  return (
    <section aria-labelledby="records-title" className="min-w-0">
      <h2 id="records-title" className={sectionTitle}>
        Your bests
      </h2>
      <dl className="mt-3 divide-y divide-line border-y border-line">
        {shown.map(([label, record, format]) =>
          record ? (
            <div
              key={label}
              className="flex min-h-12 items-center justify-between gap-4 py-2"
            >
              <dt className="text-[16px] text-ink-2">{label}</dt>
              <dd className="text-right">
                <Link
                  href={`/player/sessions/${record.session_id}`}
                  className={`inline-flex min-h-11 items-center gap-2 rounded-lg text-[16px] font-semibold tabular-nums hover:underline hover:underline-offset-4 ${focus}`}
                >
                  {format(record.value)}
                  <span className="text-[13px] font-normal text-muted">
                    {sessionDate(record.started_at)}
                  </span>
                </Link>
              </dd>
            </div>
          ) : null,
        )}
      </dl>
    </section>
  );
}

export default async function SessionsPage() {
  const { token } = await requirePlayerSession("/player/sessions");
  const [list, summary] = await Promise.all([
    fetchSessions(token),
    fetchSessionSummary(token, 12),
  ]);
  const sessions = list.data;

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <h1 className={pageTitle}>Sessions</h1>
        <Link href="/player/sessions/new" className={primaryButton}>
          <Timer size={20} strokeWidth={2} aria-hidden="true" />
          Record a session
        </Link>
      </div>
      <p className="mt-3 max-w-[60ch] text-[16px] leading-6 text-ink-2">
        Your phone&apos;s GPS measures distance, speed and sprints. Your exact
        location stays on your phone; only the totals and a grid of where you
        spent time are saved, for one year.
      </p>
      <Link href="/player/team" className={`${textLink} mt-2`}>
        <Users size={18} strokeWidth={2} aria-hidden="true" />
        Team board
      </Link>

      {sessions === null || summary.data === null ? (
        <p role="alert" className={`${errorBox} mt-8`}>
          Your sessions could not be loaded. Try again in a moment.
        </p>
      ) : sessions.length === 0 ? (
        <section
          aria-labelledby="sessions-empty-title"
          className="mt-8 max-w-[680px] rounded-xl border border-dashed border-control-border px-5 py-8 md:px-8"
        >
          <h2 id="sessions-empty-title" className={sectionTitle}>
            No sessions yet
          </h2>
          <p className="mt-2 text-[16px] leading-6 text-ink-2">
            Take your phone to training or a match, start recording, and keep it
            in a pocket or armband.
          </p>
          <Link href="/player/sessions/new" className={`${primaryButton} mt-5`}>
            <Timer size={20} strokeWidth={2} aria-hidden="true" />
            Record a session
          </Link>
        </section>
      ) : (
        <div className="mt-8 grid gap-10 lg:grid-cols-12 lg:gap-x-8">
          <section
            aria-labelledby="weeks-title"
            className="min-w-0 lg:col-span-8"
          >
            <h2 id="weeks-title" className={sectionTitle}>
              Last 12 weeks
            </h2>
            <div className="mt-4">
              <WeeklyChart weeks={summary.data.weeks} />
            </div>
          </section>
          <div className="lg:col-span-4">
            <Records records={summary.data.records} />
          </div>
          <section
            aria-labelledby="all-sessions-title"
            className="min-w-0 lg:col-span-12"
          >
            <h2 id="all-sessions-title" className={sectionTitle}>
              All sessions
            </h2>
            <ul className="mt-3 divide-y divide-line border-y border-line">
              {sessions.map((session) => (
                <li key={session.id}>
                  <Link
                    href={`/player/sessions/${session.id}`}
                    className={`group flex min-h-16 items-center gap-3 py-3 hover:bg-surface-subtle md:px-2 ${focus}`}
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block text-[16px] font-semibold leading-[1.35] group-hover:underline group-hover:underline-offset-4">
                        {kindLabel[session.kind]},{" "}
                        {sessionDate(session.started_at)}
                      </span>
                      <span className="mt-0.5 block text-[13px] text-muted tabular-nums">
                        {km(session.distance_m)} ·{" "}
                        {stopwatch(session.duration_s)} · {session.sprint_count}{" "}
                        {session.sprint_count === 1 ? "sprint" : "sprints"}
                      </span>
                    </span>
                    <ChevronRight
                      size={18}
                      strokeWidth={2}
                      aria-hidden="true"
                      className="shrink-0 text-muted"
                    />
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        </div>
      )}
    </div>
  );
}
