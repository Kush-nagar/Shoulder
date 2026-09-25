import { Bone, Loading } from "../../../../skeletons";

/** The marking workspace: player bar, video stage, clip column. */
export default function ReviewLoading() {
  return (
    <Loading label="Loading review">
      <div className="flex items-center gap-3 border-b border-line px-5 py-3 md:px-6">
        <Bone className="h-6 w-24" />
        <Bone className="h-6 w-40" />
      </div>
      <div className="grid gap-6 px-5 py-6 md:px-6 lg:grid-cols-12">
        <div className="lg:col-span-8">
          <Bone className="aspect-video rounded-[14px]" />
          <Bone className="mt-3 h-12" />
        </div>
        <div className="space-y-3 lg:col-span-4">
          {[0, 1, 2, 3, 4].map((key) => (
            <Bone key={key} className="h-16 rounded-xl" />
          ))}
        </div>
      </div>
    </Loading>
  );
}
