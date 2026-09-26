import { Bone, Loading } from "../../../../skeletons";

/** The marking workspace: context bar, night stage, clip inspector. */
export default function ReviewLoading() {
  return (
    <Loading
      label="Loading review"
      className="sh-review fixed inset-0 z-30 overflow-y-auto bg-paper"
    >
      <div className="flex min-h-14 items-center gap-4 border-b border-line bg-rail px-4 md:px-5">
        <Bone className="h-5 w-28 rounded-sm" />
        <Bone className="h-5 w-44 rounded-sm" />
      </div>
      <div className="mx-auto grid max-w-[1680px] gap-4 p-4 md:p-5 xl:grid-cols-[minmax(0,1fr)_minmax(360px,420px)] xl:gap-5 xl:p-6">
        <div>
          <Bone className="mb-2 h-4 w-24 rounded-sm" />
          <Bone className="aspect-video rounded-2xl" />
          <Bone className="mt-px h-24 rounded-2xl" />
        </div>
        <Bone className="h-[420px] rounded-2xl" />
      </div>
    </Loading>
  );
}
