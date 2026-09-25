import { drills } from "../../../content/drills";
import { fetchRoster, fetchTeamPlans, fetchTeams } from "../../../lib/api";
import { mondayOf, weekLabel } from "../../../lib/plans";
import { requireCoach } from "../session";
import { PageHeader } from "../shell";
import { componentTitle, metadata, panel, sectionTitle } from "../ui";
import { PlanEditor } from "./plan-editor";
import { PlanCard } from "./plan-list";

export const dynamic = "force-dynamic";

const drillOptions = drills.map(({ slug, title, focus }) => ({
  slug,
  title,
  focus,
}));

export default async function Plans({
  searchParams,
}: {
  searchParams: Promise<{ player?: string }>;
}) {
  const token = await requireCoach("/coach/plans");
  const team = (await fetchTeams(token))?.[0];
  const [roster, plans] = team
    ? await Promise.all([
        fetchRoster(token, team.team_id, true),
        fetchTeamPlans(token, team.team_id),
      ])
    : [null, null];
  const body = "px-5 py-6 md:px-6 lg:px-8";
  if (!team || roster === null || plans === null) {
    return (
      <>
        <PageHeader title="Plans" />
        <section className={body}>
          <p role="alert" className="text-[15px] leading-[1.5] text-error">
            {team
              ? "Plans could not be loaded and nothing was changed. Reload the page to try again."
              : "Your account is not attached to a team, so there are no plans yet."}
          </p>
        </section>
      </>
    );
  }
  const names = new Map(
    roster.map((player) => [player.id, player.display_name]),
  );
  const players = roster
    .filter((player) => player.active)
    .map((player) => ({ id: player.id, name: player.display_name }));
  const requested = (await searchParams).player;
  const defaultTarget = players.some((player) => player.id === requested)
    ? (requested as string)
    : "team";
  const thisWeek = mondayOf(new Date());
  const editor = { drills: drillOptions, players, thisWeek };
  const weeks = [...new Set(plans.map((plan) => plan.week_of))];

  return (
    <>
      <PageHeader
        title="Plans"
        description="Weekly drills for one player or the whole team."
      />
      <div
        className={`${body} grid gap-8 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]`}
      >
        <section
          aria-labelledby="new-plan-title"
          className={`${panel} h-fit p-5 xl:sticky xl:top-6`}
        >
          <h2 id="new-plan-title" className={componentTitle}>
            New plan
          </h2>
          <p className={`${metadata} mt-1`}>
            Pick a week, who it is for, and 1 to 8 drills from the library.
          </p>
          <div className="mt-4">
            <PlanEditor {...editor} defaultTarget={defaultTarget} />
          </div>
        </section>
        <section aria-labelledby="plans-title" className="min-w-0">
          <h2 id="plans-title" className={sectionTitle}>
            All plans
          </h2>
          {weeks.length === 0 ? (
            <p className="mt-3 max-w-170 text-[15px] leading-[1.5] text-muted">
              No plans yet. The first one you save shows up here and on your
              players’ home screens.
            </p>
          ) : (
            weeks.map((week) => (
              <section key={week} aria-label={weekLabel(week)} className="mt-5">
                <p className="text-[13px] font-semibold tracking-wide text-muted uppercase">
                  {weekLabel(week)}
                  {week === thisWeek ? " · This week" : ""}
                </p>
                <div className="mt-2 space-y-3">
                  {plans
                    .filter((plan) => plan.week_of === week)
                    .map((plan) => (
                      <PlanCard
                        key={plan.id}
                        plan={plan}
                        names={names}
                        editor={editor}
                      />
                    ))}
                </div>
              </section>
            ))
          )}
        </section>
      </div>
    </>
  );
}
