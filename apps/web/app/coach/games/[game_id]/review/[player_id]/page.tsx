import { ArrowLeft, Target } from "lucide-react";
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
  searchParams,
}: {
  params: Promise<{ game_id: string; player_id: string }>;
  searchParams: Promise<{ judgment?: string }>;
}) {
  const { token, userId } = await requireCoachSession();
  const { game_id: gameId, player_id: playerId } = await params;
  const { judgment } = await searchParams;
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
    <div className="sh-review fixed inset-0 z-30 overflow-y-auto bg-paper">
      <header className="sticky top-0 z-10 flex min-h-14 flex-wrap items-center gap-x-5 gap-y-2 border-b border-line bg-rail px-4 py-2 md:px-5">
        <Link
          href={`/coach/games/${game.id}`}
          className={`-ml-1 inline-flex h-9 items-center gap-1.5 rounded-md px-2 text-[13px] font-medium text-ink-2 hover:bg-surface-subtle hover:text-ink ${focus}`}
        >
          <ArrowLeft size={16} strokeWidth={1.75} aria-hidden="true" />
          Back to match
        </Link>
        <span
          aria-hidden="true"
          className="hidden h-5 w-px bg-line-strong sm:block"
        />
        <div className="flex min-w-0 items-baseline gap-3">
          <h1 className="truncate text-[15px] font-semibold">
            {player.jersey_number !== null &&
            player.jersey_number !== undefined ? (
              <span className="mr-2 font-mono text-[12px] font-normal text-muted">
                {player.jersey_number}
              </span>
            ) : null}
            {player.display_name}
          </h1>
          <p className="hidden truncate font-mono text-[12px] text-muted sm:block">
            {context}
          </p>
        </div>
        <p className="ml-auto flex min-w-0 max-w-[46ch] items-center gap-2 text-[13px] text-ink-2">
          <Target
            size={15}
            strokeWidth={1.75}
            aria-hidden="true"
            className="shrink-0 text-signal"
          />
          <span className="sr-only">Active goal: </span>
          <span className="truncate">
            {player.active_goal?.title ?? "No active development goal"}
          </span>
        </p>
      </header>

      <main className="mx-auto max-w-[1680px] p-4 md:p-5 xl:p-6">
        <p className={`${metadata} mb-3 md:hidden`}>
          A wider screen makes precise marking easier. Keyboard controls still
          work here.
        </p>
        <CoachPlayer
          videoId={ready.id}
          coachId={userId}
          playerId={player.id}
          goalId={player.active_goal?.id ?? null}
          label={context}
          initialObservations={observations}
          initialJudgmentId={judgment}
        />
      </main>
    </div>
  );
}
