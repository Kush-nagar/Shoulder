import Link from "next/link";
import { DevelopmentTimeline } from "../../../components/development-timeline";
import { fetchEvidence, fetchGoals, fetchReflections } from "../../../lib/api";
import type { TimelineGoal } from "../../../lib/development-timeline";
import { requirePlayerSession } from "../session";
import { ReflectionList } from "./reflection-list";

const focus =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

export default async function PlayerProgressPage() {
  const { token, player } = await requirePlayerSession();
  const [goals, reflections] = await Promise.all([
    fetchGoals(token, player.id),
    fetchReflections(token),
  ]);
  const evidence = goals
    ? await Promise.all(goals.map((goal) => fetchEvidence(token, goal.id)))
    : null;
  const timelineUnavailable =
    goals === null ||
    evidence === null ||
    evidence.some((sets) => sets === null);
  const timeline: TimelineGoal[] = timelineUnavailable
    ? []
    : goals.map((goal, goalIndex) => ({
        id: goal.id,
        title: goal.title,
        active: goal.status === "active",
        games: (evidence[goalIndex] ?? []).map((set) => ({
          publicationId: set.publication_id,
          gameLabel: set.game_label,
          publishedAt: set.published_at,
          dots: set.items.map((item) => ({
            judgmentId: item.judgment_id,
            verdict: item.verdict,
            href: `/player/goals/${goal.id}?publication=${set.publication_id}&judgment=${item.judgment_id}`,
          })),
          reflections: (reflections ?? [])
            .filter((reflection) =>
              set.items.some(
                (item) => item.judgment_id === reflection.judgment_id,
              ),
            )
            .map((reflection) => ({
              judgmentId: reflection.judgment_id,
              text: reflection.text,
            })),
        })),
      }));
  return (
    <div>
      <Link
        href="/player"
        className={`inline-flex min-h-11 items-center text-[16px] underline underline-offset-4 ${focus}`}
      >
        Back to your clips
      </Link>
      <h1 className="mt-5 text-[26px] font-semibold">Progress</h1>

      <section aria-labelledby="evidence-title" className="mt-8">
        <h2 id="evidence-title" className="text-[21px] font-semibold">
          Evidence by game
        </h2>
        {timelineUnavailable ? (
          <p role="alert" className="mt-4 text-[16px] leading-6 text-error">
            Your evidence record could not be loaded. Try again.
          </p>
        ) : timeline.length === 0 ? (
          <p className="mt-4 text-[16px] leading-6 text-muted">
            Your coach hasn&apos;t set a goal yet.
          </p>
        ) : (
          <div className="mt-4">
            <DevelopmentTimeline
              goals={timeline}
              reflectionLabel="Your reflection"
            />
          </div>
        )}
      </section>

      <section aria-labelledby="reflection-title" className="mt-10">
        <h2 id="reflection-title" className="text-[21px] font-semibold">
          Your reflections
        </h2>
        <p className="mt-2 text-[16px] leading-6 text-muted">
          You can edit or permanently delete any reflection you wrote.
        </p>
        {reflections === null ? (
          <p role="alert" className="mt-4 text-[16px] leading-6 text-error">
            Your reflections could not be loaded. Try again.
          </p>
        ) : (
          <ReflectionList
            playerId={player.id}
            initialReflections={reflections}
          />
        )}
      </section>
    </div>
  );
}
