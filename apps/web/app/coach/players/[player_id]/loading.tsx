import { Bone, CoachHead, Loading } from "../../skeletons";

export default function PlayerLoading() {
  return (
    <Loading label="Loading player">
      <CoachHead title="w-52" />
      <div className="max-w-[880px] space-y-4 px-5 py-6 md:px-6 lg:px-8">
        <Bone className="h-7 w-48" />
        <Bone className="h-32 rounded-xl" />
        <Bone className="h-7 w-40" />
        <Bone className="h-24 rounded-xl" />
        <Bone className="h-7 w-56" />
        <Bone className="h-48 rounded-xl" />
      </div>
    </Loading>
  );
}
