import { Bone, Loading } from "../../skeletons";

export default function DrillLoading() {
  return (
    <Loading label="Loading drill" className="max-w-[680px]">
      <Bone className="h-6 w-24" />
      <Bone className="mt-5 h-4 w-28" />
      <Bone className="mt-2 h-11 w-4/5 md:h-14" />
      <Bone className="mt-4 h-4 w-60" />
      <div className="mt-8 space-y-3 border-t border-line pt-6">
        <Bone className="h-6 w-40" />
        <Bone className="h-5 w-full" />
        <Bone className="h-5 w-11/12" />
      </div>
      <div className="mt-8 space-y-4">
        {[0, 1, 2, 3].map((key) => (
          <Bone key={key} className="h-6 w-full" />
        ))}
      </div>
    </Loading>
  );
}
