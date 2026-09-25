import { Bone, Loading } from "../../skeletons";

export default function SessionLoading() {
  return (
    <Loading label="Loading session">
      <Bone className="h-6 w-24" />
      <Bone className="mt-4 h-9 w-72 max-w-full md:h-11" />
      <Bone className="mt-2 h-4 w-40" />
      <div className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[0, 1, 2, 3].map((key) => (
          <Bone key={key} className="h-24 rounded-xl" />
        ))}
      </div>
      <Bone className="mt-10 h-6 w-40" />
      <Bone className="mt-4 aspect-[3/2] max-w-[720px] rounded-xl" />
    </Loading>
  );
}
