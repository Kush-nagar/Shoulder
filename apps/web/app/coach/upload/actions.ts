"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { apiWrite, fetchTeams, type Game } from "../../../lib/api";
import { requireCoach } from "../session";
import type { ActionState } from "../ui";

/** Plain operational copy. No provider name, status code, SQL, or key. */
function failure(status: number): string {
  if (status === 422) return "Check the fields below. Nothing was saved.";
  if (status === 401 || status === 403 || status === 404)
    return "You can no longer add a match to this team. Reload the page.";
  return "Could not save. Nothing was saved and your entry was kept. Try again.";
}

export async function createGame(
  _previous: ActionState,
  form: FormData,
): Promise<ActionState> {
  const token = await requireCoach();
  // One team per workspace: the team is resolved server-side, never posted.
  const team = (await fetchTeams(token))?.[0];
  if (!team) return { message: "No team is set up yet." };

  const playedOn = String(form.get("played_on") ?? "").trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(playedOn))
    return { message: "Enter the match date." };
  // A date input carries no time zone. Midday keeps the stored instant on the
  // day the coach picked in every zone the team could be in.
  const playedAt = new Date(`${playedOn}T12:00:00Z`);
  if (Number.isNaN(playedAt.getTime()))
    return { message: "Enter the match date." };

  const opponent = String(form.get("opponent") ?? "").trim();
  if (opponent.length > 100)
    return { message: "Opponent must be 100 characters or fewer." };
  const kind = String(form.get("kind") ?? "match");
  if (kind !== "match" && kind !== "scrimmage")
    return { message: "Choose a match or a scrimmage." };

  const reply = await apiWrite<Game>(token, "/v1/games", "POST", {
    team_id: team.team_id,
    played_at: playedAt.toISOString(),
    opponent: opponent === "" ? null : opponent,
    kind,
  });
  if (!reply.data) return { message: failure(reply.status) };
  revalidatePath("/coach/upload");
  // Straight into the upload step for the match just created.
  redirect(`/coach/upload?game=${reply.data.id}`);
}
