import Link from "next/link";
import { notFound } from "next/navigation";
import { fetchGoals, fetchRoster, fetchTeams } from "../../../../lib/api";
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
import { CloseGoal } from "./close-goal";
import { GoalForm } from "./goal-form";
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
  const team = (await fetchTeams(token))[0];
  const roster = team ? await fetchRoster(token, team.team_id) : null;
  const player = roster?.find((row) => row.id === player_id);
  // Absent, archived elsewhere, or hidden by policy all land on not-found.
  if (!player) notFound();
  const goals = (await fetchGoals(token, player.id)) ?? [];
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
                  className={`size-1.5 shrink-0 rounded-full border border-ink ${player.account_name ? "bg-ink" : ""}`}
                />
                {player.account_name ?? "Not linked"}
              </span>
              {player.account_name ? null : (
                <InvitePlayer playerId={player.id} name={player.display_name} />
              )}
            </dd>
          </div>
        </dl>

        <h2 className={`${sectionTitle} mt-8`}>Development goal</h2>
        {active ? (
          <div className={`${panel} mt-3 max-w-170 p-5`}>
            <p className="text-[17px] leading-[1.35] font-semibold">
              {active.title}
            </p>
            {active.description ? (
              <p className="mt-3 text-[15px] leading-[1.5]">
                {active.description}
              </p>
            ) : null}
            <p className={`${metadata} mt-4`}>Set {day(active.created_at)}</p>
            <div className="mt-4 border-t border-line pt-4">
              <CloseGoal
                playerId={player.id}
                goalId={active.id}
                title={active.title}
              />
            </div>
          </div>
        ) : (
          <div className="mt-3">
            <GoalForm playerId={player.id} name={player.display_name} />
          </div>
        )}

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
        <div className={`${panel} mt-3 max-w-170 border-dashed p-5`}>
          <p className="text-[15px] leading-[1.5] text-muted">
            Published clips and player reflections are not part of this version
            of Shoulder. This space is reserved for them.
          </p>
        </div>
      </section>
    </>
  );
}
