"use server";

import { revalidatePath } from "next/cache";
import { apiWrite, type Goal, type GoalStatus } from "../../../../lib/api";
import { requireCoach } from "../../session";
import type { ActionState } from "../../ui";

const closing: GoalStatus[] = ["achieved", "paused", "retired"];

export async function createGoal(
  _previous: ActionState,
  form: FormData,
): Promise<ActionState> {
  const token = await requireCoach();
  const id = String(form.get("player_id") ?? "");
  const title = String(form.get("title") ?? "").trim();
  if (title.length < 1 || title.length > 100)
    return { message: "Write a goal of 1 to 100 characters." };
  const description = String(form.get("description") ?? "").trim();
  if (description.length > 1000)
    return { message: "Keep the detail to 1000 characters or fewer." };
  const reply = await apiWrite<Goal>(token, `/v1/players/${id}/goals`, "POST", {
    title,
    description: description === "" ? null : description,
  });
  if (reply.status === 201) {
    revalidatePath(`/coach/players/${id}`);
    revalidatePath("/coach/roster");
    return { message: "Goal set.", ok: true };
  }
  if (reply.status === 409)
    return {
      message:
        "This player already has an active goal. Close that one first. Nothing was saved.",
    };
  if (reply.status === 422)
    return { message: "Check the goal text. Nothing was saved." };
  if ([401, 403, 404].includes(reply.status))
    return {
      message:
        "You can no longer change this player. Nothing was saved. Reload the page.",
    };
  return {
    message:
      "Could not save. Nothing was saved and your text was kept. Try again.",
  };
}

export async function closeGoal(
  _previous: ActionState,
  form: FormData,
): Promise<ActionState> {
  const token = await requireCoach();
  const id = String(form.get("player_id") ?? "");
  const goalId = String(form.get("goal_id") ?? "");
  const status = String(form.get("status") ?? "") as GoalStatus;
  if (!closing.includes(status))
    return { message: "Choose what happened to this goal." };
  const reply = await apiWrite<Goal>(token, `/v1/goals/${goalId}`, "PATCH", {
    status,
  });
  if (reply.status === 200) {
    revalidatePath(`/coach/players/${id}`);
    revalidatePath("/coach/roster");
    return { message: "Goal closed.", ok: true };
  }
  if (reply.status === 409)
    return {
      message: "This goal has already been closed. Nothing was changed.",
    };
  if ([401, 403, 404].includes(reply.status))
    return {
      message:
        "You can no longer change this goal. Nothing was changed. Reload the page.",
    };
  return { message: "Could not save. Nothing was changed. Try again." };
}
