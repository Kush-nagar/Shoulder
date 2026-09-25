import {
  ArrowRight,
  ChevronRight,
  Clock,
  Footprints,
  Handshake,
  Lightbulb,
  type LucideIcon,
  MapPin,
  MessageSquareQuote,
  NotebookPen,
  Play,
  Target,
  Timer,
  Video,
} from "lucide-react";
import Link from "next/link";
import { type CSSProperties, type ReactNode, Suspense } from "react";
import { Bone } from "../../components/skeleton";
import { drillOfTheDay, drillsForGoal } from "../../content/drills";
import {
  type EvidenceSet,
  fetchEvidence,
  fetchGoals,
  fetchPlayerPlans,
  fetchReflections,
  type Goal,
  type PlayerReflection,
  type TrainingPlan,
} from "../../lib/api";
import { marketplaceEnabled } from "../../lib/marketplace";
import { mondayOf } from "../../lib/plans";
import { DrillTile } from "./drills/drill-tile";
import { HowItWorks, PracticePoster } from "./home-client";
import { firstName } from "./identity";
import { PlayerPlanCard } from "./plans/plan-card";
import {
  clock,
  practiceDate,
  practiceStatus,
  practiceTitle,
} from "./practice/format";
import {
  fetchPracticeFeedback,
  fetchPracticeVideo,
  fetchPracticeVideos,
} from "./practice/server";
import type { PracticeVideo } from "./practice/types";
import { requirePlayerSession } from "./session";
import { km, minutes } from "./sessions/format";
import { fetchSessionSummary, type SessionSummary } from "./sessions/server";
import { FeedSkeleton, HeroSkeleton, WeekSkeleton } from "./skeletons";
import {
  chip,
  focus,
  primaryButton,
  secondaryButton,
  sectionTitle,
  textLink,
} from "./ui";

function shortDate(value: string) {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(new Date(value));
}

function clips(count: number) {
  return `${count} ${count === 1 ? "clip" : "clips"}`;
}

function SectionError() {
  return (
    <p
      role="alert"
      className="mt-3 rounded-xl bg-error-soft p-4 text-[16px] leading-6 text-error"
    >
      This section couldn&apos;t load.{" "}
      <a href="/player" className="font-semibold underline underline-offset-4">
        Try again
      </a>
      .
    </p>
  );
}

function Section({
  id,
  title,
  Icon,
  action,
  index,
  className = "",
  children,
}: {
  id: string;
  title: string;
  Icon?: LucideIcon;
  action?: ReactNode;
  index: number;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section
      aria-labelledby={id}
      style={{ "--i": index } as CSSProperties}
      className={`sh-rise min-w-0 ${className}`}
    >
      <div className="flex min-h-11 flex-wrap items-center justify-between gap-x-4 gap-y-1">
        <h2 id={id} className={`${sectionTitle} flex items-center gap-2.5`}>
          {Icon ? (
            <Icon
              size={20}
              strokeWidth={2}
              aria-hidden="true"
              className="shrink-0 text-brand"
            />
          ) : null}
          {title}
        </h2>
        {action}
      </div>
      {children}
    </section>
  );
}

function Dot({ verdict }: { verdict: "applied" | "opportunity" }) {
  return (
    <span
      aria-hidden="true"
      className={`inline-block size-2.5 shrink-0 rounded-full border-2 border-action ${
        verdict === "applied" ? "bg-action" : "bg-transparent"
      }`}
    />
  );
}

function GoalHero({
  goal,
  coachName,
  hasClips,
}: {
  goal: Goal | undefined;
  coachName: string | null;
  hasClips: boolean;
}) {
  return (
    <section
      aria-labelledby="working-on-title"
      style={{ "--i": 1 } as CSSProperties}
      className="sh-rise relative overflow-hidden rounded-[14px] bg-night px-5 py-6 text-on-night md:px-8 md:py-8 lg:col-span-8"
    >
      <span
        aria-hidden="true"
        className="absolute inset-y-0 left-0 w-1 bg-brand"
      />
      <h2
        id="working-on-title"
        className="flex items-center gap-2 text-[14px] font-semibold leading-[1.35] text-night-muted"
      >
        <Target size={16} strokeWidth={2} aria-hidden="true" />
        What you’re working on
      </h2>
      {goal ? (
        <>
          <p className="mt-3 font-display text-[32px] leading-[1.02] uppercase text-balance md:text-[46px]">
            {goal.title}
          </p>
          {goal.description ? (
            <p className="mt-4 max-w-[56ch] text-[16px] leading-6 text-on-night/85">
              {goal.description}
            </p>
          ) : null}
          <p className="mt-4 text-[13px] leading-[1.4] text-night-muted">
            Set by {coachName ?? "your coach"}
          </p>
          <div className="mt-6 flex flex-wrap items-center gap-x-5 gap-y-2">
            {hasClips ? (
              <Link
                href={`/player/goals/${goal.id}`}
                className={`inline-flex min-h-11 items-center gap-2 rounded-lg bg-on-night px-5 text-[16px] font-semibold text-night transition-transform duration-150 ease-out hover:-translate-y-px active:scale-[0.98] ${focus}`}
              >
                <Play
                  size={16}
                  strokeWidth={2}
                  fill="currentColor"
                  aria-hidden="true"
                />
                Watch your clips
              </Link>
            ) : null}
            <Link
              href="/player/drills"
              className={`group inline-flex min-h-11 items-center gap-1.5 rounded-lg text-[16px] font-semibold text-action-on-night underline-offset-4 hover:underline ${focus}`}
            >
              Drills for this goal
              <ChevronRight
                size={18}
                strokeWidth={2}
                aria-hidden="true"
                className="transition-transform duration-150 ease-out group-hover:translate-x-0.5"
              />
            </Link>
          </div>
        </>
      ) : (
        <p className="mt-3 font-display text-[28px] leading-[1.08] md:text-[36px]">
          Your coach hasn&apos;t set a goal yet.
        </p>
      )}
    </section>
  );
}

function LatestFromCoach({
  goal,
  evidence,
  index,
  className,
}: {
  goal: Goal;
  evidence: EvidenceSet[] | null;
  index: number;
  className?: string;
}) {
  const latest = evidence?.[0];
  return (
    <Section
      id="latest-clips-title"
      title="Latest from your coach"
      Icon={MessageSquareQuote}
      index={index}
      className={className}
    >
      {evidence === null ? (
        <SectionError />
      ) : !latest ? (
        <p className="mt-2 max-w-[52ch] text-[16px] leading-6 text-ink-2">
          Your coach&apos;s clips from your next game land here.
        </p>
      ) : (
        <div className="mt-3 overflow-hidden rounded-xl border border-line bg-surface">
          <div className="px-4 pt-4 md:px-5">
            <p className="text-[17px] font-semibold leading-[1.35]">
              {latest.game_label}
            </p>
            <p className="mt-0.5 text-[13px] text-muted tabular-nums">
              {clips(latest.items.length)}, shared{" "}
              {shortDate(latest.published_at)}
            </p>
          </div>
          <ul className="mt-3 divide-y divide-line border-t border-line">
            {latest.items.slice(0, 3).map((item, position) => (
              <li key={item.judgment_id}>
                <Link
                  href={`/player/goals/${goal.id}?publication=${latest.publication_id}&judgment=${item.judgment_id}`}
                  className={`group flex gap-3 px-4 py-3.5 transition-colors duration-150 hover:bg-surface-subtle md:px-5 ${focus}`}
                >
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2 text-[14px] font-semibold text-action">
                      <Dot verdict={item.verdict} />
                      {item.verdict_copy}
                      <span className="sr-only">, clip {position + 1}</span>
                    </span>
                    <span className="mt-1 line-clamp-2 text-[16px] leading-6 text-ink">
                      {item.comment}
                    </span>
                  </span>
                  <span className="flex shrink-0 items-center gap-1 self-start pt-0.5 text-[13px] text-muted tabular-nums">
                    <Play size={12} strokeWidth={2} aria-hidden="true" />
                    {clock(item.clip_duration_ms)}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
          {latest.items.length > 3 ? (
            <p className="border-t border-line px-4 py-3 text-[14px] text-muted md:px-5">
              {latest.items.length - 3} more in this set.
            </p>
          ) : null}
        </div>
      )}
      {evidence && evidence.length > 1 ? (
        <details className="group mt-3">
          <summary
            className={`flex min-h-11 cursor-pointer list-none items-center gap-1.5 rounded-lg text-[16px] font-semibold [&::-webkit-details-marker]:hidden ${focus}`}
          >
            <ChevronRight
              size={18}
              strokeWidth={2}
              aria-hidden="true"
              className="transition-transform duration-150 group-open:rotate-90"
            />
            Earlier games
          </summary>
          <ul className="mt-1 divide-y divide-line border-t border-line">
            {evidence.slice(1).map((set) => (
              <li key={set.publication_id}>
                <Link
                  href={`/player/goals/${goal.id}?publication=${set.publication_id}`}
                  className={`flex min-h-12 items-center justify-between gap-4 py-2 text-[16px] ${focus}`}
                >
                  <span className="font-medium">{set.game_label}</span>
                  <span className="shrink-0 text-[13px] text-muted tabular-nums">
                    {clips(set.items.length)}, {shortDate(set.published_at)}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </Section>
  );
}

async function PracticeTiles({
  token,
  videos,
}: {
  token: string;
  videos: PracticeVideo[];
}) {
  const recent = videos.slice(0, 3);
  // D5: at most three detail calls, in parallel, for short-lived poster URLs.
  const details = await Promise.all(
    recent.map((video) =>
      video.status === "ready" ? fetchPracticeVideo(token, video.id) : null,
    ),
  );
  return (
    <ul className="sh-stagger -mx-4 mt-3 flex snap-x snap-mandatory gap-3 overflow-x-auto px-4 pb-2 min-[375px]:-mx-5 min-[375px]:px-5 md:mx-0 md:grid md:grid-cols-3 md:overflow-visible md:px-0 md:pb-0">
      {recent.map((video, index) => {
        const title = practiceTitle(video.title);
        const length = clock(video.duration_ms);
        return (
          <li
            key={video.id}
            className="w-[72%] shrink-0 snap-start min-[480px]:w-[45%] md:w-auto"
          >
            <Link
              href={`/player/practice/${video.id}`}
              className={`group block rounded-lg ${focus}`}
            >
              <PracticePoster
                url={details[index]?.data?.playback_url ?? null}
                title={title}
              />
              <span className="mt-2 block truncate text-[16px] font-semibold leading-[1.35] group-hover:underline group-hover:underline-offset-4">
                {title}
              </span>
              <span className="block text-[13px] text-muted tabular-nums">
                {practiceDate(video.created_at)}
                {length ? `, ${length}` : ""}, {practiceStatus(video.status)}
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

function TilesSkeleton() {
  return (
    <div
      aria-hidden="true"
      className="mt-3 flex gap-3 overflow-hidden md:grid md:grid-cols-3"
    >
      {[0, 1, 2].map((key) => (
        <div
          key={key}
          className="w-[72%] shrink-0 min-[480px]:w-[45%] md:w-auto"
        >
          <Bone className="aspect-video" />
          <Bone className="mt-2 h-5 w-3/4" />
          <Bone className="mt-1 h-4 w-1/2" />
        </div>
      ))}
    </div>
  );
}

async function TrainingIdeas({
  token,
  videos,
}: {
  token: string;
  videos: PracticeVideo[];
}) {
  const candidates = videos
    .filter((video) => video.status === "ready")
    .slice(0, 3);
  const replies = await Promise.all(
    candidates.map((video) => fetchPracticeFeedback(token, video.id)),
  );
  if (replies.some((reply) => reply.data === null)) return <SectionError />;
  const latest = replies
    .flatMap((reply) => reply.data ?? [])
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  if (!latest) {
    return (
      <p className="mt-2 text-[16px] leading-6 text-ink-2">
        Open a practice video and choose Get training ideas.
      </p>
    );
  }
  return (
    <div className="sh-rise mt-3 rounded-xl border border-line bg-surface p-4 md:p-5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className={chip}>AI suggestion</span>
        <span className="text-[13px] text-muted tabular-nums">
          {shortDate(latest.created_at)}
        </span>
      </div>
      <ul className="mt-4 space-y-4">
        {latest.drills.slice(0, 2).map((drill) => (
          <li key={drill.title}>
            <h3 className="text-[17px] font-semibold leading-[1.35]">
              {drill.title}
            </h3>
            <p className="mt-0.5 line-clamp-2 text-[16px] leading-6 text-ink-2">
              {drill.why}
            </p>
          </li>
        ))}
      </ul>
      <Link
        href={`/player/practice/${latest.practice_video_id}`}
        className={`${textLink} group mt-2`}
      >
        Open the video
        <ArrowRight
          size={18}
          strokeWidth={2}
          aria-hidden="true"
          className="transition-transform duration-150 ease-out group-hover:translate-x-0.5"
        />
      </Link>
      <p className="mt-3 border-t border-line pt-3 text-[13px] leading-[1.4] text-muted">
        Suggestions from software. Your coach&apos;s notes come from your coach.
      </p>
    </div>
  );
}

function YourNotes({
  reflections,
  evidence,
  index,
  className,
}: {
  reflections: PlayerReflection[] | null;
  evidence: EvidenceSet[] | null;
  index: number;
  className?: string;
}) {
  const latest = reflections
    ?.slice()
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0];
  const game = latest
    ? evidence?.find((set) =>
        set.items.some((item) => item.judgment_id === latest.judgment_id),
      )
    : undefined;
  return (
    <Section
      id="notes-title"
      title="Your notes"
      Icon={NotebookPen}
      index={index}
      className={className}
      action={
        latest ? (
          <Link href="/player/progress#notes" className={textLink}>
            All notes
          </Link>
        ) : null
      }
    >
      {reflections === null ? (
        <SectionError />
      ) : latest ? (
        <figure className="mt-3 border-l-2 border-brand pl-4">
          <blockquote className="line-clamp-3 text-[16px] leading-6">
            {latest.text}
          </blockquote>
          <figcaption className="mt-2 text-[13px] text-muted tabular-nums">
            {latest.evidence_available
              ? game
                ? `On a clip from ${game.game_label}, ${shortDate(latest.updated_at)}`
                : shortDate(latest.updated_at)
              : "Clip unavailable"}
          </figcaption>
        </figure>
      ) : (
        <p className="mt-2 text-[16px] leading-6 text-ink-2">
          Optional notes you write on a clip land here.
        </p>
      )}
    </Section>
  );
}

function ThisWeek({ summary }: { summary: SessionSummary | null }) {
  const week = summary?.weeks.at(-1);
  return (
    <Section
      id="this-week-title"
      title="This week"
      Icon={Timer}
      index={3}
      className="lg:col-span-12"
      action={
        <Link href="/player/sessions" className={textLink}>
          Sessions
        </Link>
      }
    >
      {summary === null ? (
        <SectionError />
      ) : week?.sessions ? (
        <dl className="mt-3 grid grid-cols-3 gap-4 border-y border-line py-4 md:py-5">
          {(
            [
              [
                week.sessions === 1 ? "Session" : "Sessions",
                String(week.sessions),
                Timer,
              ],
              ["Distance", km(week.distance_m), MapPin],
              ["Time", minutes(week.duration_s), Clock],
            ] as const
          ).map(([label, value, StatIcon]) => (
            <div key={label} className="min-w-0">
              <dt className="flex items-center gap-1.5 text-[13px] text-muted">
                <StatIcon size={14} strokeWidth={2} aria-hidden="true" />
                {label}
              </dt>
              <dd className="mt-1 truncate font-display text-[28px] leading-none tabular-nums md:text-[34px]">
                {value}
              </dd>
            </div>
          ))}
        </dl>
      ) : (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-x-5 gap-y-3 rounded-xl bg-surface-subtle p-4 md:p-5">
          <p className="max-w-[46ch] text-[16px] leading-6 text-ink-2">
            Record training with your phone to see distance, speed and where you
            played.
          </p>
          <Link href="/player/sessions/new" className={secondaryButton}>
            <Timer size={20} strokeWidth={2} aria-hidden="true" />
            Record a session
          </Link>
        </div>
      )}
    </Section>
  );
}

function FromCoach({ plans }: { plans: TrainingPlan[] | null }) {
  // This week's plan, else the next one ahead. No plan, no card.
  const thisWeek = mondayOf(new Date());
  const weekPlans = plans?.filter((plan) => plan.week_of === thisWeek) ?? [];
  const nextPlan = [...(plans ?? [])]
    .reverse()
    .find((plan) => plan.week_of > thisWeek);
  const shownPlans = weekPlans.length ? weekPlans : nextPlan ? [nextPlan] : [];
  if (plans !== null && !shownPlans.length) return null;
  return (
    <Section
      id="plan-title"
      title="From your coach"
      Icon={NotebookPen}
      index={2}
      className="lg:col-span-12"
      action={
        plans ? (
          <Link href="/player/plans" className={textLink}>
            All plans
          </Link>
        ) : null
      }
    >
      {plans === null ? (
        <SectionError />
      ) : (
        <div className="sh-stagger mt-3 grid gap-4 lg:grid-cols-2">
          {shownPlans.slice(0, 2).map((plan) => (
            <PlayerPlanCard key={plan.id} plan={plan} />
          ))}
        </div>
      )}
    </Section>
  );
}

/** Block 10M pilot entry, shown only while the marketplace flag is on. */
function TrainWithCoach() {
  return (
    <Section
      id="coaching-title"
      title="Train with a coach"
      Icon={Handshake}
      index={6}
      className="lg:col-span-12"
    >
      <div className="mt-3 flex flex-wrap items-center justify-between gap-x-5 gap-y-3 rounded-xl bg-surface-subtle p-4 md:p-5">
        <p className="max-w-[60ch] text-[16px] leading-6 text-ink-2">
          Book 1:1 time with a verified coach. 18+ pilot, test payments only.
        </p>
        <Link href="/coaching" className={secondaryButton}>
          <Handshake size={20} strokeWidth={2} aria-hidden="true" />
          Find a coach
        </Link>
      </div>
    </Section>
  );
}

function greetingDate() {
  return new Intl.DateTimeFormat("en-GB", {
    weekday: "long",
    day: "numeric",
    month: "long",
  }).format(new Date());
}

type GoalData = {
  goals: Goal[] | null;
  goal: Goal | undefined;
  evidence: EvidenceSet[] | null;
};

async function loadGoal(token: string, playerId: string): Promise<GoalData> {
  const goals = await fetchGoals(token, playerId);
  const goal = goals?.find((item) => item.status === "active");
  const evidence = goal ? await fetchEvidence(token, goal.id) : [];
  return { goals, goal, evidence };
}

async function loadVideos(token: string) {
  const reply = await fetchPracticeVideos(token);
  return reply.data
    ?.filter((video) => video.status !== "deleted")
    .sort((a, b) => b.created_at.localeCompare(a.created_at));
}

/** First streamed row: the goal hero and today's drill. */
async function GoalRow({ data }: { data: Promise<GoalData> }) {
  const { goals, goal, evidence } = await data;
  const coachName = evidence?.[0]?.items[0]?.coach_display_name ?? null;
  return (
    <>
      {goals === null ? (
        <div className="lg:col-span-8">
          <SectionError />
        </div>
      ) : (
        <GoalHero
          goal={goal}
          coachName={coachName}
          hasClips={Boolean(evidence?.length)}
        />
      )}
      <Section
        id="today-title"
        title="Try this today"
        Icon={Footprints}
        index={2}
        className="lg:col-span-4"
      >
        <div className="mt-3 lg:h-[calc(100%-3.5rem)]">
          <DrillTile
            drill={drillOfTheDay(goal)}
            forGoal={drillsForGoal(goal).length > 0}
            showWhy
          />
        </div>
      </Section>
    </>
  );
}

async function WeekRow({
  week,
  plans,
}: {
  week: Promise<{ data: SessionSummary | null }>;
  plans: Promise<TrainingPlan[] | null>;
}) {
  const [weekReply, planList] = await Promise.all([week, plans]);
  return (
    <>
      <ThisWeek summary={weekReply.data} />
      <FromCoach plans={planList} />
    </>
  );
}

/** Clips, notes, practice and ideas: the order depends on a first run. */
async function Feed({
  token,
  goalData,
  videoList,
  reflectionList,
}: {
  token: string;
  goalData: Promise<GoalData>;
  videoList: Promise<PracticeVideo[] | undefined>;
  reflectionList: Promise<PlayerReflection[] | null>;
}) {
  const [{ goal, evidence }, videos, reflections] = await Promise.all([
    goalData,
    videoList,
    reflectionList,
  ]);
  const firstRun = !evidence?.length && !videos?.length && !reflections?.length;

  const practice = (
    <Section
      id="practice-title"
      title="Your practice"
      Icon={Video}
      index={4}
      className="lg:col-span-8"
      action={
        videos?.length ? (
          <Link href="/player/practice" className={textLink}>
            See all
          </Link>
        ) : null
      }
    >
      {videos === undefined ? (
        <SectionError />
      ) : videos.length ? (
        <>
          <Suspense fallback={<TilesSkeleton />}>
            <PracticeTiles token={token} videos={videos} />
          </Suspense>
          <Link
            href="/player/practice/new"
            className={`${secondaryButton} mt-4`}
          >
            <Video size={20} strokeWidth={2} aria-hidden="true" />
            Film practice
          </Link>
        </>
      ) : (
        <div className="mt-3 flex flex-col items-start gap-4 rounded-xl bg-surface-subtle p-5 md:flex-row md:items-center md:p-6">
          <span
            aria-hidden="true"
            className="flex size-12 shrink-0 items-center justify-center rounded-full bg-surface text-brand"
          >
            <Video size={22} strokeWidth={2} />
          </span>
          <p className="max-w-[46ch] flex-1 text-[16px] leading-6 text-ink-2">
            Film a drill and see how you moved. Only you can see it.
          </p>
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
            <Link href="/player/practice/new" className={primaryButton}>
              <Video size={20} strokeWidth={2} aria-hidden="true" />
              Film practice
            </Link>
            <Link href="/player/drills" className={textLink}>
              Browse drills
            </Link>
          </div>
        </div>
      )}
    </Section>
  );

  const ideas = videos?.length ? (
    <Section
      id="ideas-title"
      title="Training ideas"
      Icon={Lightbulb}
      index={5}
      className="lg:col-span-4"
    >
      <Suspense fallback={<Bone className="mt-3 h-56 rounded-xl" />}>
        <TrainingIdeas token={token} videos={videos} />
      </Suspense>
    </Section>
  ) : null;

  const coach = goal ? (
    <LatestFromCoach
      goal={goal}
      evidence={evidence}
      index={3}
      className={firstRun ? "lg:col-span-4" : "lg:col-span-8"}
    />
  ) : null;

  return firstRun ? (
    <>
      <HowItWorks className="lg:col-span-12" />
      {practice}
      {coach}
    </>
  ) : (
    <>
      {coach}
      <YourNotes
        reflections={reflections}
        evidence={evidence}
        index={4}
        className={goal ? "lg:col-span-4" : "lg:col-span-12"}
      />
      {practice}
      {ideas ?? <div className="hidden lg:col-span-4 lg:block" />}
      <HowItWorks className="lg:col-span-12" />
    </>
  );
}

/**
 * Home streams (ADR 0024): the greeting paints with the shell, then each row
 * arrives on its own. Every fetch starts at once; nothing waits on a sibling.
 */
export default async function PlayerHome() {
  const { token, player, me } = await requirePlayerSession();
  const goalData = loadGoal(token, player.id);
  const videoList = loadVideos(token);
  const reflectionList = fetchReflections(token);
  const week = fetchSessionSummary(token, 1);
  const plans = fetchPlayerPlans(token);
  const name = firstName(me.display_name);

  return (
    <div className="mx-auto max-w-[680px] lg:max-w-none">
      <header className="sh-rise">
        <h1 className="font-display text-[34px] leading-[1.05] md:text-[46px]">
          {name ? `Hi, ${name}.` : "Welcome to Shoulder."}
        </h1>
        <p className="mt-1 text-[14px] text-muted">{greetingDate()}</p>
      </header>

      <div className="mt-6 grid gap-8 md:mt-8 lg:grid-cols-12 lg:gap-x-8 lg:gap-y-12">
        <Suspense fallback={<HeroSkeleton />}>
          <GoalRow data={goalData} />
        </Suspense>
        <Suspense fallback={<WeekSkeleton />}>
          <WeekRow week={week} plans={plans} />
        </Suspense>
        <Suspense fallback={<FeedSkeleton />}>
          <Feed
            token={token}
            goalData={goalData}
            videoList={videoList}
            reflectionList={reflectionList}
          />
        </Suspense>
        {marketplaceEnabled() ? <TrainWithCoach /> : null}
      </div>
    </div>
  );
}
