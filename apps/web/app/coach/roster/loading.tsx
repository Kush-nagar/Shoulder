import { Bone, CoachHead, CoachRows, Loading } from "../skeletons";

export default function RosterLoading() {
  return (
    <Loading label="Loading roster">
      <CoachHead title="w-32" />
      <div className="space-y-4 px-5 py-6 md:px-6 lg:px-8">
        <Bone className="h-10 w-full max-w-sm" />
        <CoachRows count={8} />
      </div>
    </Loading>
  );
}
