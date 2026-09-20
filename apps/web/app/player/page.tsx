import Link from "next/link";
import { fetchEvidence, fetchGoals } from "../../lib/api";
import { requirePlayerSession } from "./session";

function date(value: string) {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(value));
}

export default async function PlayerHome() {
  const { token, player } = await requirePlayerSession();
  const goals = await fetchGoals(token, player.id);
  if (goals === null) {
    return (
      <section aria-labelledby="player-home-title">
        <h1
          id="player-home-title"
          className="text-[26px] font-semibold leading-[1.15]"
        >
          Your clips
        </h1>
        <p
          role="alert"
          className="mt-6 rounded-xl bg-error-soft p-4 text-[16px] leading-6 text-error"
        >
          Your clips could not be loaded. Try again in a moment.
        </p>
      </section>
    );
  }

  const goal = goals.find((item) => item.status === "active");
  const evidence = goal ? await fetchEvidence(token, goal.id) : [];

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-[32px] font-semibold leading-[1.08]">
          Your clips.
        </h1>
      </header>

      {!goal ? (
        <section aria-labelledby="working-on-title">
          <h2
            id="working-on-title"
            className="text-[14px] font-semibold leading-[1.35] text-muted"
          >
            What you’re working on
          </h2>
          <p className="mt-3 text-[16px] leading-6">
            Your coach hasn&apos;t set a goal yet.
          </p>
        </section>
      ) : (
        <>
          <section
            aria-labelledby="working-on-title"
            className="border-l-2 border-action pl-4"
          >
            <h2
              id="working-on-title"
              className="text-[14px] font-semibold leading-[1.35] text-muted"
            >
              What you’re working on
            </h2>
            <p className="mt-2 text-[21px] font-semibold leading-[1.25]">
              {goal.title}
            </p>
            {goal.description ? (
              <p className="mt-2 text-[16px] leading-6 text-ink-2">
                {goal.description}
              </p>
            ) : null}
          </section>

          {evidence === null ? (
            <p
              role="alert"
              className="rounded-xl bg-error-soft p-4 text-[16px] leading-6 text-error"
            >
              Your clips could not be loaded. Try again in a moment.
            </p>
          ) : evidence.length === 0 ? (
            <section aria-labelledby="latest-clips-title">
              <h2
                id="latest-clips-title"
                className="text-[21px] font-semibold leading-[1.25]"
              >
                Latest clips
              </h2>
              <p className="mt-3 text-[16px] leading-6">
                Your coach will add clips after a game.
              </p>
            </section>
          ) : (
            <section aria-labelledby="latest-clips-title">
              <h2
                id="latest-clips-title"
                className="text-[21px] font-semibold leading-[1.25]"
              >
                Latest clips
              </h2>
              <Link
                href={`/player/goals/${goal.id}`}
                className="mt-4 flex min-h-11 items-center justify-between gap-4 rounded-xl border border-line bg-surface p-4 text-[16px] outline-none hover:border-line-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
              >
                <span>
                  <span className="block font-semibold">
                    {evidence[0].game_label}
                  </span>
                  <span className="mt-1 block text-[13px] text-muted">
                    {evidence[0].items.length}{" "}
                    {evidence[0].items.length === 1 ? "clip" : "clips"} · Shared{" "}
                    {date(evidence[0].published_at)}
                  </span>
                </span>
                <span aria-hidden="true">View</span>
              </Link>

              {evidence.length > 1 ? (
                <div className="mt-8">
                  <h3 className="text-[17px] font-semibold leading-[1.35]">
                    Earlier games
                  </h3>
                  <ul className="mt-2 divide-y divide-line border-y border-line">
                    {evidence.slice(1).map((set) => (
                      <li key={set.publication_id}>
                        <Link
                          href={`/player/goals/${goal.id}?publication=${set.publication_id}`}
                          className="flex min-h-11 items-center justify-between gap-4 py-4 text-[16px] outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
                        >
                          <span>{set.game_label}</span>
                          <span className="text-[13px] text-muted">
                            {set.items.length}{" "}
                            {set.items.length === 1 ? "clip" : "clips"} · Shared{" "}
                            {date(set.published_at)}
                          </span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </section>
          )}
        </>
      )}
    </div>
  );
}
