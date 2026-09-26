import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowUpRight } from "lucide-react";
import { EmptyState } from "../../../components/empty-state";
import { Status } from "../../../components/status";
import { fetchGame, fetchGames, fetchTeams } from "../../../lib/api";
import { gameLabel, mainVideo, videoState, videoTone } from "../match";
import { requireCoach } from "../session";
import { PageHeader } from "../shell";
import { focusInset, metadata, panel, sectionTitle } from "../ui";
import { NewMatchForm } from "./new-match";
import { Uploader } from "./uploader";

export const dynamic = "force-dynamic";

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
        action={null}
      />
      <div className="grid gap-6 px-5 pb-8 md:px-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] lg:px-8">
        <div className="space-y-6">
          <section aria-labelledby="matches-heading">
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
              <ul
                className={`${panel} mt-3 divide-y divide-line overflow-hidden`}
              >
                {games.map((game) => {
                  const video = mainVideo(game);
                  const current = game.id === selectedId;
                  return (
                    <li key={game.id} className="relative flex items-stretch">
                      {current ? (
                        <span
                          aria-hidden="true"
                          className="absolute inset-y-2 left-0 w-0.5 rounded-r-sm bg-signal"
                        />
                      ) : null}
                      <Link
                        href={`/coach/upload?game=${game.id}`}
                        aria-current={current ? "page" : undefined}
                        className={`block min-w-0 flex-1 px-4 py-3 text-[14px] leading-[1.45] transition-colors duration-140 ${focusInset} ${
                          current ? "bg-signal-soft" : "hover:bg-surface-subtle"
                        }`}
                      >
                        <span className="block font-medium text-ink">
                          {gameLabel(game)}
                        </span>
                        <Status tone={videoTone(video)} className="mt-1">
                          {game.videos.length === 0
                            ? "No video yet"
                            : game.videos.map(videoState).join(" · ")}
                        </Status>
                      </Link>
                      {video?.status === "ready" ? (
                        <Link
                          href={`/coach/games/${game.id}`}
                          aria-label={`Open ${gameLabel(game)}`}
                          className={`flex w-12 shrink-0 items-center justify-center text-muted transition-colors duration-140 hover:bg-surface-subtle hover:text-ink ${focusInset}`}
                        >
                          <ArrowUpRight
                            size={18}
                            strokeWidth={1.75}
                            aria-hidden="true"
                          />
                        </Link>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
          <NewMatchForm />
        </div>

        {selected ? (
          <Uploader gameId={selected.id} gameLabel={gameLabel(selected)} />
        ) : (
          <EmptyState label="No match selected">
            Pick a match, or add a new one, and Shoulder will ask for its video
            file.
          </EmptyState>
        )}
      </div>
    </>
  );
}
