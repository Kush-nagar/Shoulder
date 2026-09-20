import Link from "next/link";
import { notFound } from "next/navigation";
import { DevelopmentTimeline } from "../../../../components/development-timeline";
import {
  fetchCoachEvidence,
  fetchGoals,
  fetchPlayerReflections,
  fetchRoster,
  fetchTeams,
} from "../../../../lib/api";
import type { TimelineGoal } from "../../../../lib/development-timeline";
import { requireCoach } from "../../session";
import { PageHeader } from "../../shell";
import {
  componentTitle,
  focus,
  metadata,
  panel,
  sectionTitle,
  tertiary,
} from "../../ui";
import { GoalSection } from "./goal-form";
import { InvitePlayer } from "./invite-player";

export const dynamic = "force-dynamic";

const closedLabel = {
  achieved: "Achieved",
  paused: "Paused",
  retired: "Retired",
  active: "Active",
} as const;

function day(value: string | null): string {
  if (!value) return "";
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf())
    ? ""
    : parsed.toISOString().slice(0, 10);
}

export default async function Player({
  params,
}: {
  params: Promise<{ player_id: string }>;
}) {
  const { player_id } = await params;
  const token = await requireCoach();
  const team = (await fetchTeams(token))?.[0];
  // Archived rows are requested too: archiving is soft, the roster links to
  // them, and their goals stay readable.
  const roster = team ? await fetchRoster(token, team.team_id, true) : null;
  const player = roster?.find((row) => row.id === player_id);
  // Absent or hidden by policy both land on not-found.
  if (!player) notFound();
  const goalsResult = await fetchGoals(token, player.id);
  const goals = goalsResult ?? [];
  const [evidence, reflections] = await Promise.all([
    Promise.all(
      goals.map((goal) => fetchCoachEvidence(token, player.id, goal.id)),
    ),
    fetchPlayerReflections(token, player.id),
  ]);
  const evidenceUnavailable =
    goalsResult === null || evidence.some((sets) => sets === null);
  const timeline: TimelineGoal[] = evidenceUnavailable
    ? []
    : goals.map((goal, goalIndex) => ({
        id: goal.id,
        title: goal.title,
        active: goal.status === "active",
        games: (evidence[goalIndex] ?? []).map((set) => ({
          publicationId: set.publication_id,
          gameLabel: set.game_label,
          publishedAt: set.published_at,
          dots: set.items.map((item) => ({
            judgmentId: item.judgment_id,
            verdict: item.verdict,
            href: `/coach/games/${set.game_id}/review/${player.id}?judgment=${item.judgment_id}`,
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
  const active = goals.find((goal) => goal.status === "active");
  const closed = goals.filter((goal) => goal.status !== "active");

  return (
    <>
      <PageHeader title={player.display_name} />
      <section className="px-5 py-6 md:px-6 lg:px-8">
        <p className={metadata}>
          <Link href="/coach/roster" className={tertiary}>
            Players
          </Link>
        </p>

        <dl className="mt-4 flex flex-wrap gap-x-10 gap-y-3">
          <div>
            <dt className={metadata}>Number</dt>
            <dd className="text-[15px] tabular-nums">
              {player.jersey_number ?? "Not set"}
            </dd>
          </div>
          <div>
            <dt className={metadata}>Position</dt>
            <dd className="text-[15px]">{player.position ?? "Not set"}</dd>
          </div>
          <div>
            <dt className={metadata}>Roster</dt>
            <dd className="text-[15px]">
              {player.active ? "On the roster" : "Archived"}
            </dd>
          </div>
          <div>
            <dt className={metadata}>Account</dt>
            <dd className="flex items-center gap-3 text-[15px]">
              <span className="flex items-center gap-2">
                <span
                  aria-hidden="true"
                  className={`size-1.5 shrink-0 rounded-full border border-ink ${player.account_linked ? "bg-ink" : ""}`}
                />
                {player.account_name ??
                  (player.account_linked ? "Linked" : "Not linked")}
              </span>
              <InvitePlayer
                playerId={player.id}
                name={player.display_name}
                // Archiving hides the account name but not the link, and an
                // off-roster player cannot be linked at all, so neither state
                // may offer the control.
                linkable={!player.account_linked && player.active}
              />
            </dd>
          </div>
        </dl>

        <h2 className={`${sectionTitle} mt-8`}>Development goal</h2>
        <GoalSection
          playerId={player.id}
          name={player.display_name}
          active={
            active
              ? {
                  id: active.id,
                  title: active.title,
                  description: active.description,
                  setOn: day(active.created_at),
                }
              : null
          }
        />

        {closed.length > 0 ? (
          <details className="mt-8 max-w-170">
            <summary
              className={`${componentTitle} cursor-pointer rounded-sm ${focus}`}
            >
              Closed goals ({closed.length})
            </summary>
            <ul className="mt-3 space-y-3">
              {closed.map((goal) => (
                <li key={goal.id} className="border-t border-line pt-3">
                  <p className="text-[15px] font-medium">{goal.title}</p>
                  <p className={metadata}>
                    {closedLabel[goal.status]}
                    {day(goal.closed_at) ? ` · ${day(goal.closed_at)}` : ""}
                  </p>
                </li>
              ))}
            </ul>
            <p className={`${metadata} mt-3`}>Closed goals are read-only.</p>
          </details>
        ) : null}

        <h2 className={`${sectionTitle} mt-8`}>Evidence and reflections</h2>
        <div className={`${panel} mt-3 max-w-170 p-5`}>
          {evidenceUnavailable || reflections === null ? (
            <p role="alert" className="text-[15px] leading-[1.5] text-error">
              Evidence and reflections could not be loaded. Try again.
            </p>
          ) : timeline.every((goal) => goal.games.length === 0) ? (
            <p className="text-[15px] leading-[1.5] text-muted">
              No evidence has been published for this player.
            </p>
          ) : (
            <DevelopmentTimeline
              goals={timeline}
              reflectionLabel="Player reflection"
            />
          )}
        </div>
      </section>
    </>
  );
}
