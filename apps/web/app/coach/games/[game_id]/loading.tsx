import { Bone, CoachHead, CoachRows, Loading } from "../../skeletons";

export default function MatchLoading() {
  return (
    <Loading label="Loading match">
      <CoachHead title="w-28" />
      <div className="grid gap-8 px-5 py-6 md:px-6 lg:grid-cols-12 lg:px-8">
        <div className="space-y-3 lg:col-span-5">
          <Bone className="h-7 w-52" />
          <CoachRows count={4} />
        </div>
        <div className="space-y-3 lg:col-span-7">
          <Bone className="h-7 w-20" />
          <Bone className="aspect-video rounded-[14px]" />
        </div>
      </div>
    </Loading>
  );
}
