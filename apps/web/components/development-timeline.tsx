import Link from "next/link";
import {
  evidenceDotLabel,
  sharedDate,
  type TimelineGoal,
} from "../lib/development-timeline";

const focus =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

function Dot({ filled }: { filled: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={`size-3.5 rounded-full border-2 border-ink ${filled ? "bg-ink" : "bg-transparent"}`}
    />
  );
}

export function DevelopmentTimeline({
  goals,
  reflectionLabel,
}: {
  goals: TimelineGoal[];
  reflectionLabel: "Your reflection" | "Player reflection";
}) {
  return (
    <div>
      <ul
        aria-label="Evidence legend"
        className="flex flex-wrap gap-x-5 gap-y-2 text-[14px] text-ink-2"
      >
        <li className="inline-flex items-center gap-2">
          <Dot filled /> You did this.
        </li>
        <li className="inline-flex items-center gap-2">
          <Dot filled={false} /> Chance to do this.
        </li>
      </ul>

      <div className="mt-6 space-y-8">
        {goals.map((goal) => (
          <section key={goal.id} aria-labelledby={`timeline-goal-${goal.id}`}>
            <p className="text-[13px] text-muted">
              {goal.active ? "Active goal" : "Past goal"}
            </p>
            <h3
              id={`timeline-goal-${goal.id}`}
              className="mt-1 text-[17px] font-semibold leading-[1.35]"
            >
              {goal.title}
            </h3>
            {goal.games.length === 0 ? (
              <p className="mt-3 text-[15px] leading-[1.5] text-muted">
                No published clips for this goal.
              </p>
            ) : (
              <ol className="mt-3 divide-y divide-line border-y border-line">
                {goal.games.map((game) => (
                  <li key={game.publicationId} className="py-4">
                    <div className="flex flex-wrap items-start justify-between gap-x-5 gap-y-2">
                      <div>
                        <h4 className="text-[16px] font-medium">
                          {game.gameLabel}
                        </h4>
                        <p className="mt-1 text-[13px] text-muted">
                          {game.dots.length}{" "}
                          {game.dots.length === 1 ? "clip" : "clips"} · Shared{" "}
                          {sharedDate(game.publishedAt)}
                        </p>
                      </div>
                      <ol
                        aria-label={`Clips from ${game.gameLabel}`}
                        className="flex flex-wrap gap-1"
                      >
                        {game.dots.map((dot, index) => (
                          <li key={dot.judgmentId}>
                            <Link
                              href={dot.href}
                              aria-label={evidenceDotLabel(
                                dot.verdict,
                                game.gameLabel,
                                index + 1,
                                game.dots.length,
                              )}
                              className={`flex size-11 items-center justify-center rounded-lg ${focus}`}
                            >
                              <Dot filled={dot.verdict === "applied"} />
                            </Link>
                          </li>
                        ))}
                      </ol>
                    </div>
                    {game.reflections.map((reflection) => (
                      <blockquote
                        key={reflection.judgmentId}
                        className="mt-3 border-l-2 border-line-strong pl-3 text-[15px] leading-[1.5]"
                      >
                        <p className="text-[13px] font-medium text-muted">
                          {reflectionLabel}
                        </p>
                        <p className="mt-1 whitespace-pre-wrap">
                          {reflection.text}
                        </p>
                      </blockquote>
                    ))}
                  </li>
                ))}
              </ol>
            )}
          </section>
        ))}
      </div>
    </div>
  );
}
