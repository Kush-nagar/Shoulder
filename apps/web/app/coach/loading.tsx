import { Bone, CoachHead, CoachRows, Loading } from "./skeletons";

export default function CoachDashboardLoading() {
  return (
    <Loading label="Loading">
      <CoachHead />
      <div className="grid gap-8 px-5 py-6 md:px-6 lg:grid-cols-12 lg:px-8">
        <div className="space-y-3 lg:col-span-7">
          <Bone className="h-7 w-28" />
          <CoachRows />
        </div>
        <div className="space-y-3 lg:col-span-5">
          <Bone className="h-7 w-44" />
          <Bone className="h-40 rounded-xl" />
        </div>
      </div>
    </Loading>
  );
}
