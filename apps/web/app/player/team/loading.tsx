import { Loading, PageHead, RowList } from "../skeletons";

export default function TeamLoading() {
  return (
    <Loading label="Loading team board" className="max-w-[680px]">
      <PageHead title="w-48" />
      <RowList count={6} className="mt-8" />
    </Loading>
  );
}
