import Link from "next/link";
import { notFound } from "next/navigation";
import {
  fetchGame,
  fetchGames,
  fetchTeams,
  type VideoSummary,
} from "../../../lib/api";
import { requireCoach } from "../session";
import { PageHeader } from "../shell";
import { focus, metadata, panel, sectionTitle } from "../ui";
import { NewMatchForm } from "./new-match";
import { Uploader } from "./uploader";

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
 * (`docs/05-ui.md`). Transcoding itself is Task 11, so a stored file honestly
 * reads as waiting to be prepared.
 */
function videoState(video: VideoSummary): string {
  switch (video.status) {
    case "uploading":
      return `Upload unfinished — ${video.uploaded_parts} of ${video.part_count} parts stored`;
    case "uploaded":
      return "Uploaded · preparing video";
    case "processing":
      return "Preparing video";
    case "ready":
      return "Ready";
    case "failed":
      return "This upload did not finish. Upload the file again.";
    default:
      return "Not available";
  }
}

export default async function UploadPage({
  searchParams,
}: {
  searchParams: Promise<{ game?: string }>;
}) {
  const token = await requireCoach();
  const team = (await fetchTeams(token))?.[0];
  if (!team) notFound();
  const games = await fetchGames(token, team.team_id);
  const selectedId = (await searchParams).game;
  // The list is one page; a link to an older match resolves on its own.
  const selected =
    games?.find((game) => game.id === selectedId) ??
    (selectedId ? await fetchGame(token, selectedId) : undefined);

  return (
    <>
      <PageHeader
        title="Upload match"
        description="Send one match video straight to Shoulder's private storage."
      />
      <div className="grid gap-6 px-5 py-6 md:px-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] lg:px-8">
        <div className="space-y-6">
          <section className={`${panel} p-5`} aria-labelledby="matches-heading">
            <h2 id="matches-heading" className={sectionTitle}>
              Matches
            </h2>
            {games === null ? (
              <p className={`${metadata} mt-2`}>
                Shoulder could not load this team&rsquo;s matches. Reload the
                page.
              </p>
            ) : games.length === 0 ? (
              <p className={`${metadata} mt-2`}>
                No match yet. Add the first one to upload its video.
              </p>
            ) : (
              <ul className="mt-3 space-y-2">
                {games.map((game) => (
                  <li key={game.id}>
                    <Link
                      href={`/coach/upload?game=${game.id}`}
                      aria-current={game.id === selectedId ? "page" : undefined}
                      className={`block rounded-lg border p-3 text-[15px] leading-[1.5] ${focus} ${
                        game.id === selectedId
                          ? "border-ink bg-line/40"
                          : "border-line hover:bg-line/25"
                      }`}
                    >
                      <span className="block font-medium">
                        {gameLabel(game)}
                      </span>
                      <span className={`${metadata} mt-0.5 block`}>
                        {game.videos.length === 0
                          ? "No video yet"
                          : game.videos.map(videoState).join(" · ")}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <NewMatchForm />
        </div>

        {selected ? (
          <Uploader gameId={selected.id} gameLabel={gameLabel(selected)} />
        ) : (
          <section className={`${panel} p-5`}>
            <h2 className={sectionTitle}>Choose a match</h2>
            <p className={`${metadata} mt-2`}>
              Pick a match on the left, or add a new one, and Shoulder will ask
              for its video file.
            </p>
          </section>
        )}
      </div>
    </>
  );
}
