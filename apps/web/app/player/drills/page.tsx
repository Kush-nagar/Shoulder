import { ListChecks, Target } from "lucide-react";
import Link from "next/link";
import {
  drills,
  drillsForGoal,
  focuses,
  focusFromSlug,
  focusSlug,
} from "../../../content/drills";
import { fetchGoals } from "../../../lib/api";
import { SectionHeading } from "../heading";
import { requirePlayerSession } from "../session";
import { pageTitle, focus as ring, textLink } from "../ui";
import { DrillTile } from "./drill-tile";

const chipBase = `inline-flex min-h-11 items-center rounded-full border px-4 text-[15px] font-semibold transition-[background-color,color,transform] duration-150 ease-out ${ring}`;

export default async function DrillsPage({
  searchParams,
}: {
  searchParams: Promise<{ focus?: string }>;
}) {
  const { token, player } = await requirePlayerSession("/player/drills");
  const selected = focusFromSlug((await searchParams).focus);
  const goals = await fetchGoals(token, player.id);
  const goal = goals?.find((item) => item.status === "active");
  const forGoal = drillsForGoal(goal);
  const goalSlugs = new Set(forGoal.map((drill) => drill.slug));
  const shown = selected
    ? drills.filter((drill) => drill.focus === selected)
    : drills.filter((drill) => !goalSlugs.has(drill.slug));

  return (
    <div>
      <h1 className={pageTitle}>Drills</h1>
      <p className="mt-3 max-w-[56ch] text-[16px] leading-6 text-ink-2">
        Coach-written drills for players 13 to 18. Pick one, film it, see how
        you moved.
      </p>

      {!selected && forGoal.length ? (
        <section aria-labelledby="goal-drills-title" className="mt-8 md:mt-10">
          <SectionHeading id="goal-drills-title" Icon={Target}>
            For your goal
          </SectionHeading>
          <p className="mt-1 text-[14px] leading-5 text-muted">{goal?.title}</p>
          <ul className="sh-stagger mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 lg:gap-4">
            {forGoal.map((drill, index) => (
              <li
                key={drill.slug}
                className={
                  index === 0 && forGoal.length !== 2 ? "sm:col-span-2" : ""
                }
              >
                <DrillTile drill={drill} forGoal featured={index === 0} />
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section aria-labelledby="all-drills-title" className="mt-10">
        <SectionHeading id="all-drills-title" Icon={ListChecks}>
          {selected
            ? `${selected} drills`
            : forGoal.length
              ? "More drills"
              : "All drills"}
        </SectionHeading>
        <nav aria-label="Filter by focus" className="mt-4">
          <ul className="flex flex-wrap gap-2">
            {[undefined, ...focuses].map((item) => {
              const current = item === selected;
              return (
                <li key={item ?? "all"}>
                  <Link
                    href={
                      item
                        ? `/player/drills?focus=${focusSlug(item)}`
                        : "/player/drills"
                    }
                    aria-current={current ? "true" : undefined}
                    scroll={false}
                    className={`${chipBase} ${
                      current
                        ? "border-signal bg-signal-soft text-ink active:scale-[0.97]"
                        : "border-control-border text-ink-2 hover:bg-surface-subtle hover:text-ink active:scale-[0.97]"
                    }`}
                  >
                    {item ?? "All"}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>

        {shown.length ? (
          <ul
            key={selected ?? "all"}
            className="sh-stagger mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 lg:gap-4"
          >
            {shown.map((drill) => (
              <li key={drill.slug}>
                <DrillTile drill={drill} forGoal={goalSlugs.has(drill.slug)} />
              </li>
            ))}
          </ul>
        ) : (
          <div className="mt-6">
            <p className="text-[16px] leading-6 text-ink-2">
              No drills with that focus yet.
            </p>
            <Link href="/player/drills" className={textLink}>
              Show all
            </Link>
          </div>
        )}
      </section>
    </div>
  );
}
