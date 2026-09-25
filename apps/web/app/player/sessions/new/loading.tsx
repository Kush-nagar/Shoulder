import { Bone, Loading } from "../../skeletons";

export default function RecordLoading() {
  return (
    <Loading label="Loading" className="max-w-[680px]">
      <Bone className="h-6 w-24" />
      <Bone className="mt-4 h-9 w-64 md:h-11" />
      <Bone className="mt-3 h-5 w-full" />
      <Bone className="mt-8 h-48 rounded-xl" />
    </Loading>
  );
}
