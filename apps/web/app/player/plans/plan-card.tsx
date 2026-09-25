import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { drillBySlug } from "../../../content/drills";
import type { TrainingPlan } from "../../../lib/api";
import { weekLabel } from "../../../lib/plans";
import { focus } from "../ui";

/** One coach-written plan: drills link to the library, notes are the coach's. */
export function PlayerPlanCard({
  plan,
  headingLevel = 3,
}: {
  plan: TrainingPlan;
  headingLevel?: 2 | 3;
}) {
  const Heading = headingLevel === 2 ? "h2" : "h3";
  return (
    <article className="rounded-xl border border-line bg-surface">
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 px-4 pt-4 md:px-5">
        <Heading className="text-[17px] font-semibold leading-[1.35]">
          {plan.title}
        </Heading>
        <p className="text-[13px] text-muted tabular-nums">
          {weekLabel(plan.week_of)} ·{" "}
          {plan.player_id ? "Just for you" : "Whole team"}
        </p>
      </header>
      <ol className="mt-3 divide-y divide-line border-t border-line">
        {plan.items.map((item, index) => {
          const drill = drillBySlug(item.drill_slug);
          const body = (
            <>
              <span
                aria-hidden="true"
                className="mt-0.5 inline-flex size-6 shrink-0 items-center justify-center rounded-full bg-action-soft text-[13px] font-semibold tabular-nums"
              >
                {index + 1}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-[16px] font-semibold leading-6">
                  {drill?.title ?? "A drill from your coach"}
                </span>
                {item.note ? (
                  <span className="mt-0.5 block text-[16px] leading-6 text-ink-2">
                    {item.note}
                  </span>
                ) : null}
                {drill ? (
                  <span className="mt-0.5 block text-[13px] text-muted tabular-nums">
                    {drill.focus}, {drill.minutes} min
                  </span>
                ) : null}
              </span>
            </>
          );
          return (
            // Items have no id; position is their identity within a plan.
            // biome-ignore lint/suspicious/noArrayIndexKey: see above
            <li key={index}>
              {drill ? (
                <Link
                  href={`/player/drills/${drill.slug}`}
                  className={`flex gap-3 px-4 py-3.5 hover:bg-surface-subtle md:px-5 ${focus}`}
                >
                  {body}
                  <ChevronRight
                    size={18}
                    strokeWidth={2}
                    aria-hidden="true"
                    className="mt-1 shrink-0 text-muted"
                  />
                </Link>
              ) : (
                <div className="flex gap-3 px-4 py-3.5 md:px-5">{body}</div>
              )}
            </li>
          );
        })}
      </ol>
    </article>
  );
}
