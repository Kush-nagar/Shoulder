import { Bone, CoachHead, CoachRows, Loading } from "../../skeletons";

/** The match page: night video stage, then the players to mark clips for. */
export default function MatchLoading() {
  return (
    <Loading label="Loading match">
      <CoachHead title="w-56" />
      <div className="grid gap-6 px-5 pb-10 md:px-6 lg:px-8 xl:grid-cols-[minmax(0,1fr)_300px]">
        <div>
          <Bone className="mb-2 h-4 w-24 rounded-sm" />
          <Bone className="aspect-video rounded-2xl" />
          <Bone className="mt-px h-24 rounded-2xl" />
        </div>
        <div className="space-y-3 xl:pt-7">
          <Bone className="h-5 w-48 rounded-sm" />
          <CoachRows count={4} />
        </div>
      </div>
    </Loading>
  );
}
