import { Bone, Loading } from "../../skeletons";

/** Back link, title, the video stage, then the analysis column. */
export default function PracticeDetailLoading() {
  return (
    <Loading label="Loading video">
      <Bone className="h-6 w-24" />
      <Bone className="mt-4 h-9 w-64 md:h-11" />
      <Bone className="mt-2 h-4 w-40" />
      <div className="mt-6 grid gap-8 lg:grid-cols-12">
        <Bone className="aspect-video rounded-[14px] lg:col-span-8" />
        <div className="space-y-3 lg:col-span-4">
          <Bone className="h-11 w-full" />
          <Bone className="h-5 w-4/5" />
          <Bone className="h-5 w-3/5" />
        </div>
      </div>
    </Loading>
  );
}
