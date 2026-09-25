import { Bone, Loading } from "../skeletons";

export default function PlansLoading() {
  return (
    <Loading label="Loading plans" className="max-w-[680px]">
      <Bone className="h-6 w-24" />
      <Bone className="mt-4 h-9 w-60 md:h-11" />
      <Bone className="mt-3 h-5 w-full" />
      <Bone className="mt-8 h-6 w-32" />
      <div className="mt-3 space-y-4">
        <Bone className="h-56 rounded-xl" />
        <Bone className="h-40 rounded-xl" />
      </div>
    </Loading>
  );
}
