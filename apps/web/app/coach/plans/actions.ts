"use server";

import { revalidatePath } from "next/cache";
import { drills } from "../../../content/drills";
import {
  apiWrite,
  fetchRoster,
  fetchTeams,
  type TrainingPlan,
} from "../../../lib/api";
import { parsePlanForm } from "../../../lib/plans";
import { requireCoach } from "../session";
import type { ActionState } from "../ui";

const slugs = new Set(drills.map((drill) => drill.slug));
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function refresh() {
  revalidatePath("/coach");
  revalidatePath("/coach/plans");
  revalidatePath("/coach/players/[player_id]", "page");
}

/** Create, or update when the form carries a plan id. Team is server-side. */
export async function savePlan(
  _previous: ActionState,
  form: FormData,
): Promise<ActionState> {
  const token = await requireCoach();
  const team = (await fetchTeams(token))?.[0];
  if (!team) return { message: "No team is set up yet. Nothing was saved." };
  // Archived rows too: an existing plan for one must stay editable.
  const roster = await fetchRoster(token, team.team_id, true);
  if (roster === null)
    return { message: "Could not load your roster. Nothing was saved." };
  const parsed = parsePlanForm(
    {
      title: String(form.get("title") ?? ""),
      week: String(form.get("week_of") ?? ""),
      target: String(form.get("target") ?? "team"),
      drills: form.getAll("drill_slug").map(String),
      notes: form.getAll("note").map(String),
    },
    slugs,
    new Set(roster.map((player) => player.id)),
  );
  if (!parsed.ok) return { message: parsed.message };
  const planId = String(form.get("plan_id") ?? "");
  if (planId && !UUID.test(planId))
    return { message: "That plan is not available. Reload the page." };
  // The target is fixed after creation; an edit sends only what may change.
  const { player_id, ...changes } = parsed.plan;
  const reply = planId
    ? await apiWrite<TrainingPlan>(
        token,
        `/v1/plans/${planId}`,
        "PATCH",
        changes,
      )
    : await apiWrite<TrainingPlan>(
        token,
        `/v1/teams/${team.team_id}/plans`,
        "POST",
        { ...changes, player_id },
      );
  if (reply.status === 200 || reply.status === 201) {
    refresh();
    return { message: planId ? "Plan updated." : "Plan saved.", ok: true };
  }
  if (reply.status === 422)
    return { message: "Check the plan fields. Nothing was saved." };
  if (reply.status === 403 || reply.status === 404)
    return { message: "You can no longer change this plan. Reload the page." };
  return { message: "Could not save the plan. Nothing was saved. Try again." };
}

export async function deletePlan(
  _previous: ActionState,
  form: FormData,
): Promise<ActionState> {
  const token = await requireCoach();
  const planId = String(form.get("plan_id") ?? "");
  if (!UUID.test(planId))
    return { message: "That plan is not available. Reload the page." };
  const reply = await apiWrite<null>(token, `/v1/plans/${planId}`, "DELETE");
  if (reply.status === 204 || reply.status === 404) {
    refresh();
    return { message: "Plan removed.", ok: true };
  }
  return { message: "Could not remove the plan. Try again." };
}
