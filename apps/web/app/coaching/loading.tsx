import { Bone, keys, Loading } from "../../components/skeleton";

/** Same geometry as the coach search: title, filter bar, card grid. */
export default function CoachingLoading() {
  return (
    <Loading label="Loading coaches">
      <Bone className="h-10 w-56 md:h-12" />
      <Bone className="mt-3 h-5 w-full max-w-[52ch]" />
      <div className="mt-7 rounded-2xl border border-line p-3 md:p-4">
        <Bone className="h-11 w-full" />
        <div className="mt-3 flex gap-2 overflow-hidden">
          {["w-14", "w-24", "w-24", "w-20", "w-24", "w-20"].map((w, n) => (
            <Bone
              key={keys(6)[n]}
              className={`h-10 shrink-0 rounded-full ${w}`}
            />
          ))}
        </div>
      </div>
      <Bone className="mt-8 h-5 w-28" />
      <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {keys(3).map((key) => (
          <div key={key} className="rounded-2xl border border-line p-5">
            <div className="flex gap-4">
              <Bone className="size-14 rounded-xl" />
              <div className="flex-1">
                <Bone className="h-6 w-36" />
                <Bone className="mt-2 h-4 w-24" />
              </div>
            </div>
            <Bone className="mt-4 h-7 w-52 rounded-full" />
            <Bone className="mt-4 h-7 w-44" />
            <div className="mt-5 flex justify-between border-t border-line pt-4">
              <Bone className="h-9 w-32" />
              <Bone className="h-9 w-14" />
            </div>
          </div>
        ))}
      </div>
    </Loading>
  );
}
