import { Bone, Loading, PageHead, RowList } from "../player/skeletons";

/** Same geometry as the coach search: title, lead, results beside filters. */
export default function CoachingLoading() {
  return (
    <Loading label="Loading coaches">
      <PageHead title="w-56" />
      <div className="mt-8 grid gap-8 lg:grid-cols-[minmax(0,1fr)_320px] lg:gap-12">
        <div className="space-y-3 lg:order-2">
          <Bone className="h-4 w-12" />
          <Bone className="h-10 w-full" />
          <Bone className="mt-4 h-4 w-20" />
          <div className="flex flex-wrap gap-2">
            {["w-20", "w-24", "w-16"].map((width) => (
              <Bone key={width} className={`h-9 rounded-full ${width}`} />
            ))}
          </div>
        </div>
        <RowList count={3} className="lg:order-1 [&>li]:py-5" />
      </div>
    </Loading>
  );
}
