import { Bone, Loading } from "../skeletons";

export default function ProfileLoading() {
  return (
    <Loading label="Loading profile" className="max-w-[680px]">
      <Bone className="mb-6 h-9 w-32 md:h-11" />
      <div className="border-t border-line py-8">
        <Bone className="h-6 w-28" />
        <div className="mt-4 flex items-center gap-4">
          <Bone className="size-14 rounded-full" />
          <div className="flex-1 space-y-2">
            <Bone className="h-5 w-40" />
            <Bone className="h-4 w-56" />
          </div>
        </div>
      </div>
      <div className="border-t border-line py-8">
        <Bone className="h-6 w-36" />
        <div className="mt-4 grid grid-cols-3 gap-2 sm:max-w-md">
          {[0, 1, 2].map((key) => (
            <Bone key={key} className="h-12" />
          ))}
        </div>
      </div>
    </Loading>
  );
}
