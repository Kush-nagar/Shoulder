import Link from "next/link";
import { drillBySlug } from "../../../content/drills";
import type { TrainingPlan } from "../../../lib/api";
import { weekLabel } from "../../../lib/plans";
import { componentTitle, focus, metadata, panel, tertiary } from "../ui";
import { DeletePlan } from "./delete-plan";
import { type DrillOption, PlanEditor, type PlayerOption } from "./plan-editor";

/** One plan: who it is for, its drills and notes, and optional edit tools. */
export function PlanCard({
  plan,
  names,
  editor,
}: {
  plan: TrainingPlan;
  names: Map<string, string>;
  editor?: {
    drills: DrillOption[];
    players: PlayerOption[];
    thisWeek: string;
  };
}) {
  const audience = plan.player_id
    ? (names.get(plan.player_id) ?? "One player")
    : "Whole team";
  return (
    <article className={`${panel} p-4 md:p-5`}>
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h3 className={componentTitle}>{plan.title}</h3>
        <p className={`${metadata} tabular-nums`}>
          {weekLabel(plan.week_of)} ·{" "}
          {plan.player_id ? (
            <Link
              href={`/coach/players/${plan.player_id}`}
              className={`${tertiary} text-[13px]`}
            >
              {audience}
            </Link>
          ) : (
            audience
          )}
        </p>
      </header>
      <ol className="mt-3 space-y-2">
        {plan.items.map((item, index) => {
          const drill = drillBySlug(item.drill_slug);
          return (
            <li
              // Items have no id; position is their identity within a plan.
              // biome-ignore lint/suspicious/noArrayIndexKey: see above
              key={index}
              className="flex gap-3 text-[14px] leading-[1.45]"
            >
              <span
                aria-hidden="true"
                className="mt-px inline-flex size-6 shrink-0 items-center justify-center rounded-md bg-surface-subtle font-mono text-[12px] text-ink-2"
              >
                {index + 1}
              </span>
              <span className="min-w-0">
                <span className="font-medium">
                  {drill?.title ?? "Drill no longer in the library"}
                </span>
                {drill ? (
                  <span className={`${metadata} ml-2`}>
                    {drill.focus} · {drill.minutes} min
                  </span>
                ) : null}
                {item.note ? (
                  <span className="block text-ink-2">{item.note}</span>
                ) : null}
              </span>
            </li>
          );
        })}
      </ol>
      {editor ? (
        <div className="mt-4 flex flex-wrap items-start gap-x-6 gap-y-3 border-t border-line pt-3">
          <details className="group min-w-0 flex-1 basis-full md:basis-auto">
            <summary
              className={`inline-flex min-h-10 cursor-pointer items-center rounded-sm text-[14px] font-medium text-ink underline decoration-line-strong underline-offset-4 hover:decoration-signal ${focus}`}
            >
              Edit plan<span className="sr-only">: {plan.title}</span>
            </summary>
            <div className="mt-3">
              <PlanEditor
                drills={editor.drills}
                players={editor.players}
                thisWeek={editor.thisWeek}
                plan={{
                  id: plan.id,
                  title: plan.title,
                  week_of: plan.week_of,
                  player_id: plan.player_id ?? null,
                  items: plan.items.map((item) => ({
                    drill_slug: item.drill_slug,
                    note: item.note ?? "",
                  })),
                }}
              />
            </div>
          </details>
          <DeletePlan planId={plan.id} title={plan.title} />
        </div>
      ) : null}
    </article>
  );
}
