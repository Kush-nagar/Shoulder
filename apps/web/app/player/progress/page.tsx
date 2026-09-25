import {
  ChevronDown,
  MessageSquareQuote,
  NotebookPen,
  Target,
  Video,
} from "lucide-react";
import Link from "next/link";
import { DevelopmentTimeline } from "../../../components/development-timeline";
import { fetchEvidence, fetchGoals, fetchReflections } from "../../../lib/api";
import type { TimelineGoal } from "../../../lib/development-timeline";
import { SectionHeading } from "../heading";
import {
  clock,
  monthLabel,
  practiceDate,
  practiceTitle,
} from "../practice/format";
import { fetchPracticeVideos } from "../practice/server";
import { requirePlayerSession } from "../session";
import { errorBox, focus, pageTitle } from "../ui";
import { ReflectionList } from "./reflection-list";

function longDate(value: string) {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(value));
}

export default async function PlayerProgressPage() {
  const { token, player } = await requirePlayerSession();
  const [goals, reflections, practice] = await Promise.all([
    fetchGoals(token, player.id),
    fetchReflections(token),
    fetchPracticeVideos(token),
  ]);
  const evidence = goals
    ? await Promise.all(goals.map((goal) => fetchEvidence(token, goal.id)))
    : null;
  const timelineUnavailable =
    goals === null ||
    evidence === null ||
    evidence.some((sets) => sets === null);
  // Active goal first, then the rest as the API ordered them.
  const ordered = goals
    ? goals
        .map((goal, index) => ({ goal, sets: evidence?.[index] ?? [] }))
        .sort(
          (a, b) =>
            Number(b.goal.status === "active") -
            Number(a.goal.status === "active"),
        )
    : [];
  const timeline: TimelineGoal[] = timelineUnavailable
    ? []
    : ordered.map(({ goal, sets }) => ({
        id: goal.id,
        title: goal.title,
        active: goal.status === "active",
        games: (sets ?? []).map((set) => ({
          publicationId: set.publication_id,
          gameLabel: set.game_label,
          publishedAt: set.published_at,
          dots: set.items.map((item) => ({
            judgmentId: item.judgment_id,
            verdict: item.verdict,
            href: `/player/goals/${goal.id}?publication=${set.publication_id}&judgment=${item.judgment_id}`,
          })),
          reflections: (reflections ?? [])
            .filter((reflection) =>
              set.items.some(
                (item) => item.judgment_id === reflection.judgment_id,
              ),
            )
            .map((reflection) => ({
              judgmentId: reflection.judgment_id,
              text: reflection.text,
            })),
        })),
      }));
  const active = goals?.find((goal) => goal.status === "active");
  const past = goals?.filter((goal) => goal.status !== "active") ?? [];
  const videos =
    practice.data
      ?.filter((video) => video.status !== "deleted")
      .sort((a, b) => b.created_at.localeCompare(a.created_at)) ?? null;
  const months = new Map<string, NonNullable<typeof videos>>();
  for (const video of videos ?? []) {
    const key = monthLabel(video.created_at);
    months.set(key, [...(months.get(key) ?? []), video]);
  }
  const empty =
    !timelineUnavailable &&
    timeline.every((goal) => goal.games.length === 0) &&
    videos?.length === 0;

  return (
    <div>
      <h1 className={pageTitle}>Progress</h1>
      <p className="mt-3 max-w-[56ch] text-[16px] leading-6 text-ink-2">
        {empty
          ? "Your coach's clips and your practice line up here over the season."
          : "Every clip your coach shared, game by game, and your practice."}
      </p>

      <div className="sh-rise mt-8 grid gap-10 lg:mt-10 lg:grid-cols-12 lg:gap-8">
        <aside
          aria-label="Goal summary"
          className="space-y-6 lg:sticky lg:top-6 lg:order-2 lg:col-span-4 lg:self-start"
        >
          {active ? (
            <section
              aria-labelledby="active-goal-title"
              className="relative overflow-hidden rounded-[14px] bg-night p-5 text-on-night"
            >
              <span
                aria-hidden="true"
                className="absolute inset-y-0 left-0 w-1 bg-brand"
              />
              <h2
                id="active-goal-title"
                className="flex items-center gap-2 text-[14px] font-semibold text-night-muted"
              >
                <Target size={16} strokeWidth={2} aria-hidden="true" />
                What you’re working on
              </h2>
              <p className="mt-2 font-display text-[24px] leading-[1.05] uppercase text-balance">
                {active.title}
              </p>
              <p className="mt-3 text-[13px] text-night-muted tabular-nums">
                Since {longDate(active.created_at)}
              </p>
            </section>
          ) : null}
          {past.length ? (
            <details className="group rounded-xl border border-line">
              <summary
                className={`flex min-h-12 cursor-pointer list-none items-center justify-between rounded-xl px-4 text-[16px] font-semibold [&::-webkit-details-marker]:hidden ${focus}`}
              >
                Past goals
                <ChevronDown
                  size={18}
                  strokeWidth={2}
                  aria-hidden="true"
                  className="text-muted transition-transform duration-150 group-open:rotate-180"
                />
              </summary>
              <ul className="divide-y divide-line border-t border-line">
                {past.map((goal) => (
                  <li key={goal.id} className="px-4 py-3">
                    <p className="text-[16px] font-medium leading-6">
                      {goal.title}
                    </p>
                    <p className="text-[13px] text-muted tabular-nums">
                      {longDate(goal.created_at)} to{" "}
                      {goal.closed_at ? longDate(goal.closed_at) : "now"}
                    </p>
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </aside>

        <div className="min-w-0 space-y-12 lg:order-1 lg:col-span-8">
          <section aria-labelledby="evidence-title">
            <SectionHeading id="evidence-title" Icon={MessageSquareQuote}>
              From your coach
            </SectionHeading>
            {timelineUnavailable ? (
              <p role="alert" className={`${errorBox} mt-4`}>
                Your clips could not be loaded. Try again.
              </p>
            ) : timeline.length === 0 ? (
              <p className="mt-3 text-[16px] leading-6 text-ink-2">
                Your coach hasn&apos;t set a goal yet.
              </p>
            ) : (
              <div className="mt-4">
                <DevelopmentTimeline
                  goals={timeline}
                  reflectionLabel="Your reflection"
                />
              </div>
            )}
          </section>

          <section
            aria-labelledby="practice-log-title"
            className="border-t border-line pt-8"
          >
            <SectionHeading id="practice-log-title" Icon={Video}>
              Practice log
            </SectionHeading>
            {videos === null ? (
              <p role="alert" className={`${errorBox} mt-4`}>
                Your practice videos could not be loaded. Try again.
              </p>
            ) : videos.length === 0 ? (
              <p className="mt-3 text-[16px] leading-6 text-ink-2">
                Videos you film show up here.{" "}
                <Link
                  href="/player/practice/new"
                  className="font-semibold text-action underline underline-offset-4"
                >
                  Film practice
                </Link>
              </p>
            ) : (
              [...months].map(([month, items]) => (
                <div key={month} className="mt-5">
                  <h3 className="text-[14px] font-semibold text-ink-2">
                    {month}
                  </h3>
                  <ul className="mt-1 divide-y divide-line border-y border-line">
                    {items.map((video) => {
                      const length = clock(video.duration_ms);
                      return (
                        <li key={video.id}>
                          <Link
                            href={`/player/practice/${video.id}`}
                            className={`flex min-h-12 items-center justify-between gap-4 py-2 text-[16px] hover:underline hover:underline-offset-4 ${focus}`}
                          >
                            <span className="min-w-0 truncate font-medium">
                              {practiceTitle(video.title)}
                            </span>
                            <span className="shrink-0 text-[13px] text-muted tabular-nums">
                              {practiceDate(video.created_at)}
                              {length ? `, ${length}` : ""}
                            </span>
                          </Link>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              ))
            )}
          </section>

          <section
            id="notes"
            aria-labelledby="reflection-title"
            className="scroll-mt-20 border-t border-line pt-8"
          >
            <SectionHeading id="reflection-title" Icon={NotebookPen}>
              Your notes
            </SectionHeading>
            <p className="mt-2 text-[15px] leading-6 text-muted">
              Edit or permanently delete any note you wrote.
            </p>
            {reflections === null ? (
              <p role="alert" className={`${errorBox} mt-4`}>
                Your notes could not be loaded. Try again.
              </p>
            ) : (
              <ReflectionList
                playerId={player.id}
                initialReflections={reflections}
              />
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
