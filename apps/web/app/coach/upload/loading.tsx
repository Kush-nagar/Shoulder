import { Bone, CoachHead, CoachRows, Loading } from "../skeletons";

export default function UploadLoading() {
  return (
    <Loading label="Loading matches">
      <CoachHead title="w-44" />
      <div className="grid gap-8 px-5 py-6 md:px-6 lg:grid-cols-12 lg:px-8">
        <div className="space-y-3 lg:col-span-5">
          <Bone className="h-7 w-28" />
          <CoachRows count={4} />
        </div>
        <div className="space-y-3 lg:col-span-7">
          <Bone className="h-7 w-40" />
          <Bone className="h-56 rounded-xl" />
        </div>
      </div>
    </Loading>
  );
}
