import { notFound } from "next/navigation";
import { fetchGame, type VideoSummary } from "../../../../lib/api";
import { PageHeader } from "../../shell";
import { requireCoach } from "../../session";
import { metadata, panel, sectionTitle } from "../../ui";
import { CoachPlayer } from "./player";

export const dynamic = "force-dynamic";

const dateLabel = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

function gameLabel(game: {
  opponent: string | null;
  played_at: string;
  kind: string;
}) {
  const when = dateLabel.format(new Date(game.played_at));
  const who = game.opponent ? `vs ${game.opponent}` : "No opponent recorded";
  return `${who} · ${when}${game.kind === "scrimmage" ? " · Scrimmage" : ""}`;
}

/**
 * Plain stages, never an animated percentage the worker cannot measure
 * (`docs/05-ui.md`).
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

export default async function GamePage({
  params,
}: {
  params: Promise<{ game_id: string }>;
}) {
  const token = await requireCoach();
  const { game_id } = await params;
  const game = await fetchGame(token, game_id);
  // Absent and hidden share one surface, so a coach outside the team learns
  // nothing about whether the match exists.
  if (!game) notFound();

  const ready = game.videos.find((video) => video.status === "ready");

  return (
    <>
      <PageHeader title="Match" description={gameLabel(game)} />
      <div className="grid gap-6 px-5 py-6 md:px-6 lg:px-8">
        {ready ? (
          <CoachPlayer videoId={ready.id} label={gameLabel(game)} />
        ) : (
          <section className={`${panel} p-5`}>
            <h2 className={sectionTitle}>Video</h2>
            {game.videos.length === 0 ? (
              <p className={`${metadata} mt-2`}>
                No video yet. Upload the match file to review it here.
              </p>
            ) : (
              <ul className={`${metadata} mt-2 space-y-1`}>
                {game.videos.map((video) => (
                  <li key={video.id}>{stage(video)}</li>
                ))}
              </ul>
            )}
          </section>
        )}
      </div>
    </>
  );
}
