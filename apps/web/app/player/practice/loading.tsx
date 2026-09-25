import { Loading, PageHead, TileGrid } from "../skeletons";

export default function PracticeLoading() {
  return (
    <Loading label="Loading practice">
      <PageHead title="w-40" action />
      <TileGrid />
    </Loading>
  );
}
