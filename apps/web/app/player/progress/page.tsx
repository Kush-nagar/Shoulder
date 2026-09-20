import Link from "next/link";
import { fetchReflections } from "../../../lib/api";
import { requirePlayerSession } from "../session";
import { ReflectionList } from "./reflection-list";

const focus =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

export default async function PlayerProgressPage() {
  const { token, player } = await requirePlayerSession();
  const reflections = await fetchReflections(token);
  if (reflections === null) {
    return <p role="alert">Your reflections could not be loaded. Try again.</p>;
  }
  return (
    <section aria-labelledby="reflection-title">
      <Link
        href="/player"
        className={`inline-flex min-h-11 items-center text-[16px] underline underline-offset-4 ${focus}`}
      >
        Back to your clips
      </Link>
      <h1 id="reflection-title" className="mt-5 text-[26px] font-semibold">
        Your reflections
      </h1>
      <p className="mt-2 text-[16px] leading-6 text-muted">
        You can edit or permanently delete any reflection you wrote.
      </p>
      <ReflectionList playerId={player.id} initialReflections={reflections} />
    </section>
  );
}
