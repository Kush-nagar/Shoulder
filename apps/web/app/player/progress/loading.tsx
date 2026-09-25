import { Bone, Loading, PageHead, RowList, SectionHead } from "../skeletons";

export default function ProgressLoading() {
  return (
    <Loading label="Loading progress">
      <PageHead title="w-40" />
      <div className="mt-8 grid gap-10 lg:mt-10 lg:grid-cols-12 lg:gap-8">
        <Bone className="h-40 rounded-[14px] lg:order-2 lg:col-span-4" />
        <div className="space-y-12 lg:order-1 lg:col-span-8">
          <div>
            <SectionHead width="w-40" />
            <RowList count={3} className="mt-4" />
          </div>
          <div>
            <SectionHead width="w-32" />
            <RowList count={3} className="mt-4" />
          </div>
        </div>
      </div>
    </Loading>
  );
}
