import { Bone, keys, Loading } from "../../../components/skeleton";

/** Title, the two tabs, then booking cards. */
export default function BookingsLoading() {
  return (
    <Loading label="Loading bookings" className="max-w-[860px]">
      <Bone className="h-10 w-52 md:h-12" />
      <div className="mt-8 flex gap-4 border-b border-line pb-3">
        <Bone className="h-6 w-28" />
        <Bone className="h-6 w-44" />
      </div>
      <div className="mt-5 space-y-3">
        {keys(2).map((key) => (
          <div key={key} className="rounded-2xl border border-line p-4 md:p-5">
            <div className="flex gap-4">
              <Bone className="size-12 rounded-xl" />
              <div className="flex-1">
                <Bone className="h-5 w-48" />
                <Bone className="mt-2 h-6 w-36" />
                <Bone className="mt-2 h-4 w-56 max-w-full" />
              </div>
            </div>
            <Bone className="mt-4 h-9 w-40" />
          </div>
        ))}
      </div>
    </Loading>
  );
}
