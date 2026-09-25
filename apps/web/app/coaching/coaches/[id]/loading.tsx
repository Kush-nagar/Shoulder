import { Bone, Loading } from "../../../player/skeletons";

/** Coach profile beside the booking column. */
export default function CoachDetailLoading() {
  return (
    <Loading label="Loading coach">
      <Bone className="h-6 w-28" />
      <div className="mt-4 grid gap-10 lg:grid-cols-[minmax(0,6fr)_minmax(0,5fr)] lg:gap-14">
        <div>
          <Bone className="h-10 w-64 md:h-12" />
          <Bone className="mt-3 h-5 w-52" />
          <div className="mt-6 grid grid-cols-2 gap-x-6 gap-y-4 border-y border-line py-5 sm:grid-cols-3">
            {[0, 1, 2].map((key) => (
              <div key={key}>
                <Bone className="h-4 w-12" />
                <Bone className="mt-1.5 h-6 w-20" />
              </div>
            ))}
          </div>
          <Bone className="mt-6 h-5 w-full" />
          <Bone className="mt-2 h-5 w-5/6" />
        </div>
        <div className="space-y-3">
          <Bone className="h-6 w-40" />
          {[0, 1, 2, 3].map((key) => (
            <Bone key={key} className="h-12" />
          ))}
        </div>
      </div>
    </Loading>
  );
}
