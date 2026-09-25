import { Bone, Loading } from "../../skeletons";

/** The clip stage and its verdict card, then the clip strip. */
export default function ClipsLoading() {
  return (
    <Loading label="Loading your clips">
      <Bone className="h-6 w-24" />
      <Bone className="mt-4 h-9 w-72 max-w-full md:h-11" />
      <div className="mt-6 grid gap-6 lg:grid-cols-12">
        <Bone className="aspect-video rounded-[14px] lg:col-span-8" />
        <div className="space-y-3 lg:col-span-4">
          <Bone className="h-5 w-32" />
          <Bone className="h-6 w-full" />
          <Bone className="h-6 w-4/5" />
          <Bone className="mt-6 h-28 rounded-xl" />
        </div>
      </div>
    </Loading>
  );
}
