import {
  Loading,
  PageHead,
  RowList,
  SectionHead,
} from "../../player/skeletons";

export default function BookingsLoading() {
  return (
    <Loading label="Loading bookings" className="max-w-[760px]">
      <PageHead title="w-52" />
      <div className="mt-8">
        <SectionHead width="w-28" />
        <RowList count={3} />
      </div>
    </Loading>
  );
}
