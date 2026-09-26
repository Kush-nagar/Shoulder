import { ArrowRight, ChevronRight, Upload } from "lucide-react";
import Link from "next/link";
import { EmptyState } from "../../components/empty-state";
import { Status } from "../../components/status";
import {
  fetchCoachEvidence,
  fetchGames,
  fetchRoster,
  fetchTeamPlans,
  fetchTeams,
  type Game,
} from "../../lib/api";
import { mondayOf, weekLabel } from "../../lib/plans";
import { mainVideo, matchDate, videoState, videoTone } from "./match";
import { PlanCard } from "./plans/plan-list";
import { requireCoach } from "./session";
import { PageHeader } from "./shell";
import {
  focusInset,
  metadata,
  panel,
  primary,
  row,
  sectionTitle,
  tertiary,
} from "./ui";

export const dynamic = "force-dynamic";

function shortDate(value: string) {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(new Date(value));
}

const more = `sh-nudge inline-flex min-h-9 items-center gap-1 rounded-sm text-[13px] font-medium text-ink-2 hover:text-ink ${focusInset}`;

function Unavailable({ what }: { what: string }) {
  return (
    <p role="alert" className="mt-3 text-[14px] leading-[1.5] text-error">
      {what} could not be loaded. Reload the page to try again.
    </p>
  );
}

function SectionHead({
  id,
  title,
  href,
  link,
}: {
  id: string;
  title: string;
  href?: string;
  link?: string;
}) {
  return (
    <div className="flex min-h-9 items-center justify-between gap-3">
      <h2 id={id} className={sectionTitle}>
        {title}
      </h2>
      {href ? (
        <Link href={href} className={more}>
          {link}
          <ArrowRight size={14} strokeWidth={1.75} aria-hidden="true" />
        </Link>
      ) : null}
    </div>
  );
}

/** One match row: where the footage stands and the one next step. */
function MatchRow({ game }: { game: Game }) {
  const video = mainVideo(game);
  const ready = video?.status === "ready";
  const href =
    ready || video
      ? `/coach/games/${game.id}`
      : `/coach/upload?game=${game.id}`;
  return (
    <li>
      <Link href={href} className={`${row} group`}>
        <span className="hidden w-24 shrink-0 whitespace-nowrap font-mono text-[12px] text-muted sm:block">
          {matchDate(game)}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[14px] font-medium text-ink">
            {game.opponent ? `vs ${game.opponent}` : "No opponent recorded"}
            {game.kind === "scrimmage" ? (
              <span className="ml-2 font-normal text-muted">Scrimmage</span>
            ) : null}
          </span>
          <span className="mt-0.5 flex flex-wrap items-center gap-x-3 sm:hidden">
            <span className="font-mono text-[12px] text-muted">
              {matchDate(game)}
            </span>
            <Status tone={videoTone(video)}>
              {video ? videoState(video) : "No video yet"}
            </Status>
          </span>
        </span>
        <span className="hidden w-[190px] shrink-0 sm:block">
          <Status tone={videoTone(video)} className="max-w-full">
            <span className="truncate">
              {video ? videoState(video) : "No video yet"}
            </span>
          </Status>
        </span>
        <span className="hidden w-[92px] shrink-0 text-right text-[13px] text-ink-2 group-hover:text-ink md:block">
          {ready ? "Review" : video ? "Open" : "Upload video"}
        </span>
        <ChevronRight
          size={16}
          strokeWidth={1.75}
          aria-hidden="true"
          className="shrink-0 text-muted transition-transform duration-140 group-hover:translate-x-0.5 group-hover:text-ink"
        />
      </Link>
    </li>
  );
}

export default async function CoachDashboard() {
  const token = await requireCoach("/coach");
  const teams = await fetchTeams(token);
  const team = teams?.[0];
  if (!team) {
    return (
      <>
        <PageHeader title="This week" />
        <section className="px-5 pb-8 md:px-6 lg:px-8">
          {teams === null ? (
            <Unavailable what="Your team" />
          ) : (
            <EmptyState label="No team yet">
              Your account is not attached to a team yet. Ask whoever set up
              Shoulder for your club to add you.
            </EmptyState>
          )}
        </section>
      </>
    );
  }
  const [roster, plans, games] = await Promise.all([
    fetchRoster(token, team.team_id),
    fetchTeamPlans(token, team.team_id),
    fetchGames(token, team.team_id),
  ]);
  const players = roster ?? [];
  const withGoal = players.flatMap((player) =>
    player.active_goal ? [{ ...player, goalId: player.active_goal.id }] : [],
  );
  // ponytail: one evidence call per player with a goal (a roster is ~25).
  // Add a team-level endpoint if rosters grow.
  const evidence = await Promise.all(
    withGoal.map((player) =>
      fetchCoachEvidence(token, player.id, player.goalId),
    ),
  );
  const evidenceFailed = evidence.some((sets) => sets === null);
  const recent = withGoal
    .flatMap((player, index) =>
      (evidence[index] ?? []).map((set) => ({ player, set })),
    )
    .sort((a, b) => b.set.published_at.localeCompare(a.set.published_at))
    .slice(0, 6);
  const thisWeek = mondayOf(new Date());
  const weekPlans = (plans ?? []).filter((plan) => plan.week_of === thisWeek);
  const names = new Map(
    players.map((player) => [player.id, player.display_name]),
  );
  const noGoal = players.length - withGoal.length;
  const matches = (games ?? []).slice(0, 6);

  return (
    <>
      <PageHeader title="This week" description={weekLabel(thisWeek)} />
      <div className="grid gap-x-10 gap-y-10 px-5 pb-12 md:px-6 lg:grid-cols-12 lg:px-8">
        <div className="min-w-0 space-y-10 lg:col-span-7">
          <section aria-labelledby="matches-title">
            <SectionHead
              id="matches-title"
              title="Matches"
              href={matches.length ? "/coach/upload" : undefined}
              link="All matches"
            />
            {games === null ? (
              <Unavailable what="Your matches" />
            ) : matches.length === 0 ? (
              <EmptyState
                label="No matches yet"
                className="mt-3"
                action={
                  <Link href="/coach/upload" className={primary}>
                    <Upload size={16} strokeWidth={2} aria-hidden="true" />
                    Upload match
                  </Link>
                }
              >
                Upload your first game to start a review.
              </EmptyState>
            ) : (
              <ul
                className={`${panel} mt-3 divide-y divide-line overflow-hidden`}
              >
                {matches.map((game) => (
                  <MatchRow key={game.id} game={game} />
                ))}
              </ul>
            )}
          </section>

          <section aria-labelledby="squad-title">
            <SectionHead
              id="squad-title"
              title="Players"
              href="/coach/roster"
              link="Roster"
            />
            {roster === null ? (
              <Unavailable what="Your roster" />
            ) : players.length === 0 ? (
              <EmptyState
                label="No players yet"
                className="mt-3"
                action={
                  <Link href="/coach/roster" className={primary}>
                    Build your roster
                  </Link>
                }
              >
                Add your squad to set goals and mark clips for each player.
              </EmptyState>
            ) : (
              <>
                <p className={`${metadata} mt-0.5`}>
                  {players.length} on the roster
                  {noGoal ? `, ${noGoal} without a goal yet` : ""}
                </p>
                <ul
                  className={`${panel} mt-3 divide-y divide-line overflow-hidden`}
                >
                  {players.map((player) => (
                    <li key={player.id}>
                      <Link
                        href={`/coach/players/${player.id}`}
                        className={`${row} group`}
                      >
                        <span className="w-7 shrink-0 font-mono text-[12px] text-muted">
                          {player.jersey_number ?? ""}
                        </span>
                        <span className="w-[34%] min-w-0 shrink-0 truncate text-[14px] font-medium">
                          {player.display_name}
                        </span>
                        <span
                          className={`min-w-0 flex-1 truncate text-[13px] ${player.active_goal ? "text-ink-2" : "text-muted"}`}
                        >
                          {player.active_goal?.title ?? "Set a goal"}
                        </span>
                        <ChevronRight
                          size={16}
                          strokeWidth={1.75}
                          aria-hidden="true"
                          className="shrink-0 text-muted transition-transform duration-140 group-hover:translate-x-0.5 group-hover:text-ink"
                        />
                      </Link>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </section>
        </div>

        <div className="min-w-0 space-y-10 lg:col-span-5">
          <section aria-labelledby="published-title">
            <SectionHead id="published-title" title="Recently shared clips" />
            {evidenceFailed ? (
              <Unavailable what="Shared clips" />
            ) : recent.length === 0 ? (
              <p className="mt-2 text-[14px] leading-[1.5] text-muted">
                Clips you publish to a player show up here.
              </p>
            ) : (
              <ul
                className={`${panel} mt-3 divide-y divide-line overflow-hidden`}
              >
                {recent.map(({ player, set }) => (
                  <li key={set.publication_id}>
                    <Link
                      href={`/coach/players/${player.id}`}
                      className={`${row} justify-between py-2.5`}
                    >
                      <span className="min-w-0">
                        <span className="block text-[14px] font-medium">
                          {player.display_name}
                        </span>
                        <span className={`${metadata} block truncate`}>
                          {set.game_label}
                        </span>
                      </span>
                      <span className="shrink-0 font-mono text-[12px] text-muted">
                        {set.items.length}{" "}
                        {set.items.length === 1 ? "clip" : "clips"} ·{" "}
                        {shortDate(set.published_at)}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section aria-labelledby="week-plans-title">
            <SectionHead
              id="week-plans-title"
              title="Plans this week"
              href="/coach/plans"
              link="All plans"
            />
            {plans === null ? (
              <Unavailable what="Plans" />
            ) : weekPlans.length === 0 ? (
              <p className="mt-2 text-[14px] leading-[1.5] text-muted">
                No plan for this week yet.{" "}
                <Link href="/coach/plans" className={tertiary}>
                  Make a plan
                </Link>{" "}
                with a few drills for the team or one player.
              </p>
            ) : (
              <div className="mt-3 space-y-3">
                {weekPlans.map((plan) => (
                  <PlanCard key={plan.id} plan={plan} names={names} />
                ))}
              </div>
            )}
          </section>
        </div>
      </div>
    </>
  );
}
