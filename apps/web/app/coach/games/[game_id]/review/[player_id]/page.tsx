import Link from "next/link";
import { notFound } from "next/navigation";
import {
  fetchGame,
  fetchObservations,
  fetchRoster,
} from "../../../../../../lib/api";
import { requireCoachSession } from "../../../../session";
import { focus, metadata } from "../../../../ui";
import { CoachPlayer } from "../../player";

export const dynamic = "force-dynamic";

const dateLabel = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

export default async function ReviewPage({
  params,
}: {
  params: Promise<{ game_id: string; player_id: string }>;
}) {
  const { token, userId } = await requireCoachSession();
  const { game_id: gameId, player_id: playerId } = await params;
  const game = await fetchGame(token, gameId);
  if (!game) notFound();

  const [roster, ready] = [
    await fetchRoster(token, game.team_id),
    game.videos.find((video) => video.status === "ready"),
  ];
  const player = roster?.find(
    (candidate) => candidate.id === playerId && candidate.active,
  );
  if (!player || !ready) notFound();

  const observations = await fetchObservations(token, ready.id, player.id);
  if (!observations) notFound();

  const when = dateLabel.format(new Date(game.played_at));
  const match = game.opponent ? `vs ${game.opponent}` : "Match";
  const context = `${match} · ${when}`;

  return (
    <div className="fixed inset-0 z-30 overflow-y-auto bg-paper">
      <header className="sticky top-0 z-10 flex flex-wrap items-center justify-between gap-3 border-b border-line bg-paper px-5 py-3 md:px-6 lg:px-8">
        <div className="flex items-center gap-4">
          <Link
            href={`/coach/games/${game.id}`}
            className={`text-[15px] underline underline-offset-2 ${focus}`}
          >
            Back to match
          </Link>
          <div>
            <h1 className="text-[17px] font-semibold">{player.display_name}</h1>
            <p className={metadata}>{context}</p>
          </div>
        </div>
        <p className={metadata}>
          {player.active_goal?.title ?? "No active development goal"}
        </p>
      </header>

      <main className="mx-auto max-w-360 p-4 md:p-6 lg:p-8">
        <p className={`${metadata} mb-3 md:hidden`}>
          A wider screen makes precise marking easier. Keyboard controls still
          work here.
        </p>
        <CoachPlayer
          videoId={ready.id}
          coachId={userId}
          playerId={player.id}
          goalId={player.active_goal?.id ?? null}
          label={`${player.display_name} · ${context}`}
          initialObservations={observations}
        />
      </main>
    </div>
  );
}
