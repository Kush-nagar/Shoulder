import { Bone, Loading, PageHead } from "../../player/skeletons";

export default function CoachOnboardingLoading() {
  return (
    <Loading label="Loading coach profile" className="max-w-[760px]">
      <PageHead title="w-64" />
      <div className="mt-8 space-y-4">
        <Bone className="h-24 rounded-xl" />
        <Bone className="h-4 w-24" />
        <Bone className="h-10 w-full" />
        <Bone className="h-4 w-24" />
        <Bone className="h-28 w-full" />
      </div>
    </Loading>
  );
}
