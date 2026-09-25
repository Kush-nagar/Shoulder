import { Bone, Loading } from "../../skeletons";

export default function FilmPracticeLoading() {
  return (
    <Loading label="Loading">
      <Bone className="h-6 w-24" />
      <div className="mt-4 grid gap-10 lg:grid-cols-12 lg:gap-8">
        <div className="max-w-[680px] lg:col-span-7">
          <Bone className="h-9 w-56 md:h-11" />
          <Bone className="mt-3 h-5 w-full" />
          <Bone className="mt-5 h-20 rounded-xl" />
          <Bone className="mt-6 h-44 rounded-xl" />
          <Bone className="mt-5 h-11 w-32" />
        </div>
        <div className="space-y-3 lg:col-span-5">
          <Bone className="h-6 w-36" />
          {[0, 1, 2, 3].map((key) => (
            <Bone key={key} className="h-5 w-full" />
          ))}
        </div>
      </div>
    </Loading>
  );
}
