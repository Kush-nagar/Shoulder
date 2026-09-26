import { Check, ChevronRight } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { EmptyState } from "../../../../components/empty-state";
import { fetchGame, fetchRoster, type VideoSummary } from "../../../../lib/api";
import { gameLabel, matchDate } from "../../match";
import { requireCoachSession } from "../../session";
import { PageHeader } from "../../shell";
import { focusInset, metadata, panel, primary, sectionTitle } from "../../ui";
import { CoachPlayer } from "./player";

export const dynamic = "force-dynamic";

const STAGES = ["Uploaded", "Preparing video", "Ready"] as const;

/**
 * Plain stages, never an animated percentage the worker cannot measure
 * (`docs/05-ui.md`). Only states the API reports are shown.
 */
function stage(video: VideoSummary): string {
  switch (video.status) {
    case "uploading":
      return `Uploading — ${video.uploaded_parts} of ${video.part_count} parts stored`;
    case "uploaded":
      return "Uploaded · preparing video";
    case "processing":
      return "Preparing video";
    case "ready":
      return "Ready";
    case "failed":
      return "This video could not be prepared. Upload the file again.";
    default:
      return "Not available";
  }
}

function stageIndex(video: VideoSummary): number {
  if (video.status === "uploaded") return 0;
  if (video.status === "processing") return 1;
  if (video.status === "ready") return 2;
  return -1;
}

/** Where a video is in preparation, as the three literal stages. */
function Processing({ video }: { video: VideoSummary }) {
  const at = stageIndex(video);
  const working = video.status === "uploaded" || video.status === "processing";
  return (
    <div className="overflow-hidden rounded-2xl bg-night text-on-night ring-1 ring-night-line">
      <div className="flex h-56 flex-col items-center justify-center gap-4 px-6 text-center md:h-72">
        <span
          aria-hidden="true"
          className="relative block h-px w-48 overflow-hidden bg-night-line"
        >
          {working ? (
            <span className="sh-scan absolute inset-y-0 left-0 w-12 bg-action-on-night/70" />
          ) : null}
        </span>
        <p className="text-[15px]">{stage(video)}</p>
      </div>
      {at >= 0 ? (
        <ol className="grid grid-cols-3 border-t border-night-line">
          {STAGES.map((name, index) => (
            <li
              key={name}
              aria-current={index === at ? "step" : undefined}
              className={`flex items-center gap-2 px-4 py-3 text-[13px] ${
                index < at
                  ? "text-night-muted"
                  : index === at
                    ? "text-on-night"
                    : "text-night-muted/60"
              }`}
            >
              {index < at ? (
                <Check size={14} strokeWidth={2} aria-hidden="true" />
              ) : (
                <span
                  aria-hidden="true"
                  className={`size-1.5 rounded-full ${index === at ? "bg-action-on-night" : "bg-night-line"}`}
                />
              )}
              {name}
            </li>
          ))}
        </ol>
      ) : null}
    </div>
  );
}

export default async function GamePage({
  params,
}: {
  params: Promise<{ game_id: string }>;
}) {
  const { game_id } = await params;
  const { token, userId } = await requireCoachSession(
    `/coach/games/${game_id}`,
  );
  const game = await fetchGame(token, game_id);
  // Absent and hidden share one surface, so a coach outside the team learns
  // nothing about whether the match exists.
  if (!game) notFound();

  const ready = game.videos.find((video) => video.status === "ready");
  const roster = ready ? await fetchRoster(token, game.team_id) : null;
  const latest = game.videos.at(-1);

  return (
    <>
      <PageHeader
        title={game.opponent ? `vs ${game.opponent}` : "Match"}
        crumb={{ href: "/coach", label: "Dashboard" }}
        description={
          <span className="font-mono text-[12px]">
            {matchDate(game)}
            {game.kind === "scrimmage" ? " · Scrimmage" : ""}
          </span>
        }
      />
      <div className="grid gap-6 px-5 pb-10 md:px-6 lg:px-8 xl:grid-cols-[minmax(0,1fr)_300px]">
        {ready ? (
          <>
            <CoachPlayer
              videoId={ready.id}
              coachId={userId}
              label={gameLabel(game)}
            />
            <section aria-labelledby="mark-heading" className="min-w-0 xl:pt-7">
              <h2 id="mark-heading" className={sectionTitle}>
                Mark clips for a player
              </h2>
              <p className={`${metadata} mt-1`}>
                Clips are marked for one player and their active goal.
              </p>
              {roster?.length ? (
                <ul
                  className={`${panel} mt-3 divide-y divide-line overflow-hidden`}
                >
                  {roster.map((player) => (
                    <li key={player.id}>
                      <Link
                        href={`/coach/games/${game.id}/review/${player.id}`}
                        className={`group flex items-center gap-3 px-4 py-2.5 transition-colors duration-140 hover:bg-surface-subtle ${focusInset}`}
                      >
                        <span className="w-6 shrink-0 font-mono text-[12px] text-muted">
                          {player.jersey_number ?? ""}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[14px] font-medium">
                            {player.display_name}
                          </span>
                          <span className={`${metadata} block truncate`}>
                            {player.active_goal?.title ??
                              "No active development goal"}
                          </span>
                        </span>
                        <ChevronRight
                          size={16}
                          strokeWidth={1.75}
                          aria-hidden="true"
                          className="shrink-0 text-muted transition-transform duration-140 group-hover:translate-x-0.5 group-hover:text-ink"
                        />
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className={`${metadata} mt-3`}>
                  Add an active player before marking clips.
                </p>
              )}
            </section>
          </>
        ) : latest ? (
          <section aria-label="Video" className="xl:col-span-2">
            <Processing video={latest} />
            {latest.status === "failed" || latest.status === "uploading" ? (
              <Link
                href={`/coach/upload?game=${game.id}`}
                className={`${primary} mt-4`}
              >
                {latest.status === "failed"
                  ? "Upload the file again"
                  : "Continue upload"}
              </Link>
            ) : null}
          </section>
        ) : (
          <section aria-label="Video" className="xl:col-span-2">
            <EmptyState
              label="No video yet"
              action={
                <Link
                  href={`/coach/upload?game=${game.id}`}
                  className={primary}
                >
                  Upload match video
                </Link>
              }
            >
              Upload the match file to review it here.
            </EmptyState>
          </section>
        )}
      </div>
    </>
  );
}
