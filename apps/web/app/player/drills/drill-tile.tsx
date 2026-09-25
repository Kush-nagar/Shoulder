import { Clock, Package } from "lucide-react";
import Link from "next/link";
import type { Drill } from "../../../content/drills";
import { focus } from "../ui";

export function DrillMeta({
  drill,
  className = "",
}: {
  drill: Drill;
  className?: string;
}) {
  return (
    <p
      className={`flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] leading-[1.4] text-muted tabular-nums ${className}`}
    >
      <span className="inline-flex items-center gap-1.5">
        <Clock size={16} strokeWidth={2} aria-hidden="true" />
        {drill.minutes} min
      </span>
      <span>{drill.space}</span>
      <span className="inline-flex items-center gap-1.5">
        <Package size={16} strokeWidth={2} aria-hidden="true" />
        {drill.equipment}
      </span>
    </p>
  );
}

/** Typographic drill cover: focus tag, condensed title, meta. No imagery. */
export function DrillTile({
  drill,
  forGoal = false,
  featured = false,
  headingLevel = 3,
  showWhy = false,
}: {
  drill: Drill;
  forGoal?: boolean;
  featured?: boolean;
  headingLevel?: 2 | 3;
  showWhy?: boolean;
}) {
  const Heading = headingLevel === 2 ? "h2" : "h3";
  return (
    <Link
      href={`/player/drills/${drill.slug}`}
      className={`group relative flex h-full flex-col overflow-hidden rounded-xl border border-line bg-surface p-4 transition-[border-color,transform] duration-200 ease-out hover:-translate-y-0.5 hover:border-line-strong active:translate-y-0 active:scale-[0.99] md:p-5 ${focus}`}
    >
      {forGoal ? (
        <span
          aria-hidden="true"
          className="absolute inset-x-0 top-0 h-[3px] bg-brand"
        />
      ) : null}
      <span className="text-[13px] font-semibold text-action">
        {drill.focus}
        {forGoal ? (
          <span className="font-normal text-muted">, for your goal</span>
        ) : null}
      </span>
      <Heading
        className={`mt-2 font-display leading-[1.05] text-ink group-hover:underline group-hover:decoration-2 group-hover:underline-offset-4 ${
          featured ? "text-[30px] md:text-[36px]" : "text-[22px]"
        }`}
      >
        {drill.title}
      </Heading>
      {featured || showWhy ? (
        <p className="mt-3 max-w-[52ch] text-[16px] leading-6 text-ink-2">
          {drill.why}
        </p>
      ) : null}
      <DrillMeta drill={drill} className="mt-auto pt-5" />
    </Link>
  );
}
