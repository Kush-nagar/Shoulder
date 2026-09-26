import { Bone, keys, Loading } from "../../../../components/skeleton";

/** Profile hero and about beside the booking panel. */
export default function CoachDetailLoading() {
  return (
    <Loading label="Loading coach">
      <Bone className="h-6 w-28" />
      <div className="mt-4 grid grid-cols-[minmax(0,1fr)] gap-10 lg:grid-cols-[minmax(0,1fr)_400px] lg:gap-14">
        <div>
          <div className="flex flex-col gap-5 sm:flex-row sm:items-center">
            <Bone className="size-20 rounded-xl md:size-24" />
            <div>
              <Bone className="h-10 w-64 md:h-12" />
              <Bone className="mt-3 h-5 w-72 max-w-full" />
            </div>
          </div>
          <Bone className="mt-6 h-8 w-56 rounded-full" />
          <div className="mt-8 border-t border-line pt-7">
            <Bone className="h-6 w-24" />
            <Bone className="mt-4 h-5 w-full" />
            <Bone className="mt-2 h-5 w-5/6" />
            <Bone className="mt-2 h-5 w-2/3" />
          </div>
        </div>
        <div className="rounded-xl border border-line p-5 md:p-6">
          <Bone className="h-6 w-32" />
          <Bone className="mt-2 h-4 w-52" />
          <div className="mt-6 flex gap-2">
            {keys(4).map((key) => (
              <Bone key={key} className="h-[84px] w-[68px] rounded-xl" />
            ))}
          </div>
          <div className="mt-5 grid grid-cols-2 gap-2">
            {keys(4).map((key) => (
              <Bone key={key} className="h-14 rounded-xl" />
            ))}
          </div>
          <Bone className="mt-6 h-11 w-full" />
        </div>
      </div>
    </Loading>
  );
}
