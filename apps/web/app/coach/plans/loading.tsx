import { Bone, CoachHead, Loading } from "../skeletons";

export default function PlansLoading() {
  return (
    <Loading label="Loading plans">
      <CoachHead title="w-28" />
      <div className="grid gap-8 px-5 py-6 md:px-6 lg:grid-cols-12 lg:px-8">
        <Bone className="h-80 rounded-xl lg:col-span-5" />
        <div className="space-y-4 lg:col-span-7">
          <Bone className="h-7 w-32" />
          <Bone className="h-40 rounded-xl" />
          <Bone className="h-40 rounded-xl" />
        </div>
      </div>
    </Loading>
  );
}
