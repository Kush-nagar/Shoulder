import { Bone, keys, Loading } from "../../components/skeleton";

/**
 * Skeletons shaped like the pages they stand in for (ADR 0024). Flat fill
 * plus one slow shimmer; static under reduced motion. No spinners.
 */

function SectionHead({ width = "w-40" }: { width?: string }) {
  return (
    <div className="flex min-h-11 items-center gap-2.5">
      <Bone className="size-5 rounded-md" />
      <Bone className={`h-6 ${width}`} />
    </div>
  );
}

/** Page title row with an optional primary action on the right. */
export function PageHead({
  title = "w-44",
  action = false,
  lead = true,
}: {
  title?: string;
  action?: boolean;
  lead?: boolean;
}) {
  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <Bone className={`h-9 md:h-11 ${title}`} />
        {action ? <Bone className="h-11 w-44" /> : null}
      </div>
      {lead ? <Bone className="mt-3 h-5 w-full max-w-[44ch]" /> : null}
    </>
  );
}

export function HeroSkeleton() {
  return (
    <>
      <Loading label="Loading your goal" className="lg:col-span-8">
        <Bone className="h-[280px] rounded-[14px] md:h-[320px]" />
      </Loading>
      <div aria-hidden="true" className="lg:col-span-4">
        <SectionHead width="w-36" />
        <Bone className="mt-3 h-[236px] rounded-xl lg:h-[calc(320px-3.5rem)]" />
      </div>
    </>
  );
}

export function WeekSkeleton() {
  return (
    <div aria-hidden="true" className="lg:col-span-12">
      <SectionHead width="w-28" />
      <div className="mt-3 grid grid-cols-3 gap-4 border-y border-line py-4 md:py-5">
        {[0, 1, 2].map((key) => (
          <div key={key}>
            <Bone className="h-4 w-16" />
            <Bone className="mt-2 h-8 w-20 md:h-9" />
          </div>
        ))}
      </div>
    </div>
  );
}

export function FeedSkeleton() {
  return (
    <>
      <Loading
        label="Loading your clips and practice"
        className="lg:col-span-8"
      >
        <SectionHead width="w-52" />
        <Bone className="mt-3 h-64 rounded-xl" />
      </Loading>
      <div aria-hidden="true" className="lg:col-span-4">
        <SectionHead width="w-32" />
        <Bone className="mt-3 h-5 w-full" />
        <Bone className="mt-2 h-5 w-4/5" />
        <Bone className="mt-2 h-5 w-3/5" />
      </div>
    </>
  );
}

/** Video tiles: a list row on phones, a card grid from 768 px. */
export function TileGrid({ count = 6 }: { count?: number }) {
  return (
    <div className="mt-8 grid gap-3 md:mt-10 md:grid-cols-2 md:gap-x-4 md:gap-y-6 lg:grid-cols-3">
      {keys(count).map((key) => (
        <div key={key} className="flex items-center gap-3 md:block">
          <Bone className="aspect-video w-24 shrink-0 md:w-full" />
          <div className="flex-1 md:mt-2">
            <Bone className="h-5 w-3/4" />
            <Bone className="mt-1.5 h-4 w-1/2" />
          </div>
        </div>
      ))}
    </div>
  );
}

/** Drill covers: tall cards in a responsive grid. */
export function CardGrid({ count = 6 }: { count?: number }) {
  return (
    <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 lg:gap-4">
      {keys(count).map((key) => (
        <Bone key={key} className="h-44 rounded-xl" />
      ))}
    </div>
  );
}

/** Rows with a title line and a meta line, divided by hairlines. */
export function RowList({
  count = 5,
  className = "mt-3",
}: {
  count?: number;
  className?: string;
}) {
  return (
    <ul className={`divide-y divide-line border-y border-line ${className}`}>
      {keys(count).map((key) => (
        <li key={key} className="py-3.5">
          <Bone className="h-5 w-3/5 max-w-80" />
          <Bone className="mt-1.5 h-4 w-2/5 max-w-52" />
        </li>
      ))}
    </ul>
  );
}

export { Bone, Loading, SectionHead };
