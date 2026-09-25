import { Bone, Loading, PageHead, RowList, SectionHead } from "../skeletons";

export default function SessionsLoading() {
  return (
    <Loading label="Loading sessions">
      <PageHead title="w-40" action />
      <div className="mt-8 grid gap-10 lg:grid-cols-12 lg:gap-x-8">
        <div className="lg:col-span-8">
          <SectionHead width="w-36" />
          <Bone className="mt-4 h-56 rounded-xl" />
        </div>
        <div className="lg:col-span-4">
          <SectionHead width="w-28" />
          <RowList count={4} />
        </div>
        <div className="lg:col-span-12">
          <SectionHead width="w-32" />
          <RowList count={4} />
        </div>
      </div>
    </Loading>
  );
}
