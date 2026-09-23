import Link from "next/link";
import { fetchEvidence, fetchGoals } from "../../lib/api";
import { requirePlayerSession } from "./session";

const focus =
  "outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

function date(value: string) {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(value));
}

function clips(count: number) {
  return `${count} ${count === 1 ? "clip" : "clips"}`;
}

function LoadError() {
  return (
    <p
      role="alert"
      className="rounded-xl bg-error-soft p-4 text-[16px] leading-6 text-error"
    >
      Your clips could not be loaded. Try again in a moment.
    </p>
  );
}

function PracticeInvite() {
  return (
    <section
      aria-labelledby="practice-invite-title"
      className="border-t border-line pt-8"
    >
      <h2
        id="practice-invite-title"
        className="text-[21px] font-semibold leading-[1.25]"
      >
        Practice on your own
      </h2>
      <p className="mt-2 max-w-[46ch] text-[16px] leading-6 text-ink-2">
        Film a drill, see how you moved, and get training ideas. Only you can
        see these videos.
      </p>
      <Link
        href="/player/practice"
        className={`mt-4 inline-flex min-h-11 items-center rounded-lg border border-line-strong px-4 text-[16px] font-semibold transition-colors duration-150 hover:bg-surface-subtle ${focus}`}
      >
        Go to practice
      </Link>
    </section>
  );
}

export default async function PlayerHome() {
  const { token, player } = await requirePlayerSession();
  const goals = await fetchGoals(token, player.id);
  if (goals === null) {
    return (
      <section aria-labelledby="player-home-title" className="space-y-6">
        <h1
          id="player-home-title"
          className="text-[32px] font-semibold leading-[1.08]"
        >
          Your clips.
        </h1>
        <LoadError />
      </section>
    );
  }

  const goal = goals.find((item) => item.status === "active");
  const evidence = goal ? await fetchEvidence(token, goal.id) : [];
  const latest = evidence?.[0];
  const firstClip = latest?.items[0];

  return (
    <div className="space-y-10">
      <h1 className="text-[32px] font-semibold leading-[1.08] tracking-[-0.01em]">
        Your clips.
      </h1>

      <section
        aria-labelledby="working-on-title"
        className="rounded-[14px] bg-ink px-5 py-6 text-paper"
      >
        <h2
          id="working-on-title"
          className="text-[14px] font-semibold leading-[1.35] text-paper/75"
        >
          What you’re working on
        </h2>
        {goal ? (
          <>
            <p className="mt-2 text-[24px] font-semibold leading-[1.2] text-balance">
              {goal.title}
            </p>
            {goal.description ? (
              <p className="mt-3 text-[16px] leading-6 text-paper/85">
                {goal.description}
              </p>
            ) : null}
          </>
        ) : (
          <p className="mt-2 text-[18px] leading-7">
            Your coach hasn&apos;t set a goal yet.
          </p>
        )}
      </section>

      {goal ? (
        <section aria-labelledby="latest-clips-title">
          <h2
            id="latest-clips-title"
            className="text-[21px] font-semibold leading-[1.25]"
          >
            Latest from your coach
          </h2>
          {evidence === null ? (
            <div className="mt-4">
              <LoadError />
            </div>
          ) : !latest ? (
            <p className="mt-3 text-[16px] leading-6 text-ink-2">
              Your coach will add clips after a game.
            </p>
          ) : (
            <>
              <Link
                href={`/player/goals/${goal.id}`}
                className={`group mt-4 block rounded-[14px] border border-line bg-surface p-5 transition-colors duration-150 hover:border-line-strong ${focus}`}
              >
                <span className="flex items-baseline justify-between gap-4">
                  <span className="text-[17px] font-semibold leading-[1.35]">
                    {latest.game_label}
                  </span>
                  <span className="shrink-0 text-[16px] font-semibold text-action underline-offset-4 group-hover:underline">
                    Watch
                  </span>
                </span>
                <span className="mt-1 block text-[13px] text-muted tabular-nums">
                  {clips(latest.items.length)}, shared{" "}
                  {date(latest.published_at)}
                </span>
                {firstClip ? (
                  <span className="mt-4 block border-t border-line pt-4">
                    <span className="block text-[14px] font-semibold text-action">
                      {firstClip.verdict_copy}
                    </span>
                    <span className="mt-1 block text-[16px] leading-6 text-ink-2">
                      {firstClip.comment}
                    </span>
                  </span>
                ) : null}
              </Link>

              {evidence.length > 1 ? (
                <div className="mt-8">
                  <h3 className="text-[17px] font-semibold leading-[1.35]">
                    Earlier games
                  </h3>
                  <ul className="mt-2 divide-y divide-line border-t border-line">
                    {evidence.slice(1).map((set) => (
                      <li key={set.publication_id}>
                        <Link
                          href={`/player/goals/${goal.id}?publication=${set.publication_id}`}
                          className={`flex min-h-14 items-center justify-between gap-4 py-3 text-[16px] ${focus}`}
                        >
                          <span className="font-medium">{set.game_label}</span>
                          <span className="shrink-0 text-[13px] text-muted tabular-nums">
                            {clips(set.items.length)}, {date(set.published_at)}
                          </span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </>
          )}
        </section>
      ) : null}

      <PracticeInvite />
    </div>
  );
}
