import { ArrowRight } from "lucide-react";
import Link from "next/link";
import {
  fetchCoachEvidence,
  fetchRoster,
  fetchTeamPlans,
  fetchTeams,
} from "../../lib/api";
import { mondayOf, weekLabel } from "../../lib/plans";
import { PlanCard } from "./plans/plan-list";
import { requireCoach } from "./session";
import { PageHeader } from "./shell";
import {
  componentTitle,
  focus,
  metadata,
  panel,
  primary,
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

const more = `inline-flex min-h-10 items-center gap-1 rounded-sm text-[15px] font-semibold text-action hover:underline underline-offset-4 ${focus}`;

function Unavailable({ what }: { what: string }) {
  return (
    <p role="alert" className="mt-3 text-[15px] leading-[1.5] text-error">
      {what} could not be loaded. Reload the page to try again.
    </p>
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
        <section className="px-5 py-6 md:px-6 lg:px-8">
          {teams === null ? (
            <Unavailable what="Your team" />
          ) : (
            <p className="max-w-170 text-[15px] leading-[1.5] text-muted">
              Your account is not attached to a team yet. Ask whoever set up
              Shoulder for your club to add you.
            </p>
          )}
        </section>
      </>
    );
  }
  const [roster, plans] = await Promise.all([
    fetchRoster(token, team.team_id),
    fetchTeamPlans(token, team.team_id),
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

  return (
    <>
      <PageHeader title="This week" description={weekLabel(thisWeek)} />
      <div className="grid gap-8 px-5 py-6 md:px-6 lg:grid-cols-12 lg:px-8">
        <section
          aria-labelledby="squad-title"
          className="min-w-0 lg:col-span-7"
        >
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 id="squad-title" className={sectionTitle}>
              Players
            </h2>
            <Link href="/coach/roster" className={more}>
              Roster
              <ArrowRight size={16} strokeWidth={2} aria-hidden="true" />
            </Link>
          </div>
          {roster === null ? (
            <Unavailable what="Your roster" />
          ) : players.length === 0 ? (
            <p className="mt-3 text-[15px] leading-[1.5] text-muted">
              No players yet.{" "}
              <Link href="/coach/roster" className={tertiary}>
                Build your roster
              </Link>{" "}
              to start.
            </p>
          ) : (
            <>
              <p className={`${metadata} mt-1`}>
                {players.length} on the roster
                {noGoal ? `, ${noGoal} without a goal yet` : ""}
              </p>
              <ul className={`${panel} mt-3 divide-y divide-line`}>
                {players.map((player) => (
                  <li key={player.id}>
                    <Link
                      href={`/coach/players/${player.id}`}
                      className={`flex min-h-12 flex-wrap items-center justify-between gap-x-4 gap-y-1 px-4 py-2.5 hover:bg-surface-subtle ${focus}`}
                    >
                      <span className="font-medium">
                        {player.display_name}
                        {player.jersey_number !== null &&
                        player.jersey_number !== undefined ? (
                          <span className={`${metadata} ml-2 tabular-nums`}>
                            #{player.jersey_number}
                          </span>
                        ) : null}
                      </span>
                      <span
                        className={`text-[14px] ${player.active_goal ? "text-ink-2" : "text-muted"}`}
                      >
                        {player.active_goal?.title ?? "Set a goal"}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>

        <div className="min-w-0 space-y-8 lg:col-span-5">
          <section aria-labelledby="published-title">
            <h2 id="published-title" className={sectionTitle}>
              Recently shared clips
            </h2>
            {evidenceFailed ? (
              <Unavailable what="Shared clips" />
            ) : recent.length === 0 ? (
              <p className="mt-3 text-[15px] leading-[1.5] text-muted">
                Clips you publish to a player show up here.
              </p>
            ) : (
              <ul className="mt-3 space-y-2">
                {recent.map(({ player, set }) => (
                  <li key={set.publication_id}>
                    <Link
                      href={`/coach/players/${player.id}`}
                      className={`${panel} flex items-center justify-between gap-4 px-4 py-3 hover:bg-surface-subtle ${focus}`}
                    >
                      <span className="min-w-0">
                        <span className="block font-medium">
                          {player.display_name}
                        </span>
                        <span className={`${metadata} block truncate`}>
                          {set.game_label}
                        </span>
                      </span>
                      <span className={`${metadata} shrink-0 tabular-nums`}>
                        {set.items.length}{" "}
                        {set.items.length === 1 ? "clip" : "clips"},{" "}
                        {shortDate(set.published_at)}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section aria-labelledby="week-plans-title">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 id="week-plans-title" className={sectionTitle}>
                Plans this week
              </h2>
              <Link href="/coach/plans" className={more}>
                All plans
                <ArrowRight size={16} strokeWidth={2} aria-hidden="true" />
              </Link>
            </div>
            {plans === null ? (
              <Unavailable what="Plans" />
            ) : weekPlans.length === 0 ? (
              <div className={`${panel} mt-3 p-5`}>
                <p className={componentTitle}>No plan for this week yet</p>
                <p className="mt-1 text-[15px] leading-[1.5] text-muted">
                  Give the team or one player a few drills to work on.
                </p>
                <Link href="/coach/plans" className={`${primary} mt-4`}>
                  Make a plan
                </Link>
              </div>
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
