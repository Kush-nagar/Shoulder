import { Bone, CardGrid, Loading, PageHead } from "../skeletons";

const chips = ["w-14", "w-24", "w-28", "w-20", "w-32"];

export default function DrillsLoading() {
  return (
    <Loading label="Loading drills">
      <PageHead title="w-32" />
      <Bone className="mt-10 h-6 w-36" />
      <div className="mt-4 flex flex-wrap gap-2">
        {chips.map((width) => (
          <Bone key={width} className={`h-11 rounded-full ${width}`} />
        ))}
      </div>
      <CardGrid />
    </Loading>
  );
}
