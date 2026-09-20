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
  searchParams: Promise<{ publication?: string }>;
}) {
  const { goal_id: goalId } = await params;
  const { publication } = await searchParams;
  const { token, player } = await requirePlayerSession();
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
    />
  );
}
