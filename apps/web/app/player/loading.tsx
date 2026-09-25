import {
  Bone,
  FeedSkeleton,
  HeroSkeleton,
  Loading,
  WeekSkeleton,
} from "./skeletons";

/** Home before its session lands: greeting, then the streamed rows. */
export default function PlayerLoading() {
  return (
    <div className="mx-auto max-w-[680px] lg:max-w-none">
      <Loading label="Loading">
        <Bone className="h-10 w-52 md:h-12 md:w-64" />
        <Bone className="mt-2 h-4 w-40" />
      </Loading>
      <div className="mt-6 grid gap-8 md:mt-8 lg:grid-cols-12 lg:gap-x-8 lg:gap-y-12">
        <HeroSkeleton />
        <WeekSkeleton />
        <FeedSkeleton />
      </div>
    </div>
  );
}
