import { notFound } from "next/navigation";
import {
  fetchEvidence,
  fetchGoals,
  fetchReflections,
} from "../../../../lib/api";
import { requirePlayerSession } from "../../session";
import { EvidenceSequence } from "./evidence-sequence";

export default async function GoalEvidencePage({
  params,
  searchParams,
}: {
  params: Promise<{ goal_id: string }>;
  searchParams: Promise<{ publication?: string; judgment?: string }>;
}) {
  const { goal_id: goalId } = await params;
  const { publication, judgment } = await searchParams;
  // Both halves of the merge matter: the email link carries a publication and
  // the timeline carries a judgment, and either can arrive before sign-in, so
  // the destination has to survive it with whichever it was given.
  const query = new URLSearchParams();
  if (publication) query.set("publication", publication);
  if (judgment) query.set("judgment", judgment);
  const search = query.toString();
  const destination = `/player/goals/${goalId}${search ? `?${search}` : ""}`;
  const { token, player } = await requirePlayerSession(destination);
  const goals = await fetchGoals(token, player.id);
  if (goals === null) {
    return (
      <p role="alert">Your clips could not be loaded. Try again in a moment.</p>
    );
  }
  const goal = goals.find((item) => item.id === goalId);
  if (!goal) notFound();
  const [evidence, reflections] = await Promise.all([
    fetchEvidence(token, goalId),
    fetchReflections(token),
  ]);
  if (evidence === null) {
    return (
      <p role="alert">Your clips could not be loaded. Try again in a moment.</p>
    );
  }
  return (
    <EvidenceSequence
      goalId={goalId}
      goalTitle={goal.title}
      playerId={player.id}
      initialEvidence={evidence}
      initialReflections={reflections ?? []}
      reflectionsLoaded={reflections !== null}
      initialPublicationId={publication}
      initialJudgmentId={judgment}
    />
  );
}
