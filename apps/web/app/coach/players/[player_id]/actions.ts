"use server";

import { revalidatePath } from "next/cache";
import {
  apiWrite,
  type DeletionStatus,
  type Goal,
  type GoalStatus,
} from "../../../../lib/api";
import { requireCoach } from "../../session";
import type { ActionState } from "../../ui";

const closing: GoalStatus[] = ["achieved", "paused", "retired"];

/**
 * One action for both goal writes, chosen by the form's `intent`.
 *
 * Two separate `useActionState` hooks each keep their own last message, so a
 * component holding both cannot tell which fired most recently and would
 * announce a stale one. A single hook is always last-action-wins.
 */
export async function goalAction(
  previous: ActionState,
  form: FormData,
): Promise<ActionState> {
  return form.get("intent") === "close"
    ? closeGoal(previous, form)
    : createGoal(previous, form);
}

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

export async function erasePlayerData(
  _previous: ActionState,
  form: FormData,
): Promise<ActionState> {
  const token = await requireCoach();
  const playerId = String(form.get("player_id") ?? "");
  const idempotencyKey = String(form.get("idempotency_key") ?? "");
  const videoCount = Number(form.get("expected_video_count"));
  const clipCount = Number(form.get("expected_other_player_clip_count"));
  const challenge = String(form.get("challenge") ?? "");
  const confirmations = {
    collateral_deletion_confirmed:
      form.get("collateral_deletion_confirmed") === "on",
    notice_confirmed: form.get("notice_confirmed") === "on",
    unrelated_data_reviewed: form.get("unrelated_data_reviewed") === "on",
  };
  if (
    !Number.isInteger(videoCount) ||
    videoCount < 0 ||
    !Number.isInteger(clipCount) ||
    clipCount < 0 ||
    !Object.values(confirmations).every(Boolean) ||
    idempotencyKey.length < 1 ||
    idempotencyKey.length > 200
  )
    return {
      message: "Complete every deletion confirmation. Nothing was changed.",
    };

  const reply = await apiWrite<DeletionStatus>(
    token,
    `/v1/players/${playerId}/erasure`,
    "POST",
    {
      expected_video_count: videoCount,
      expected_other_player_clip_count: clipCount,
      challenge,
      ...confirmations,
    },
    { "Idempotency-Key": idempotencyKey },
  );
  if (reply.status === 202) {
    revalidatePath("/coach/roster");
    revalidatePath(`/coach/players/${playerId}`);
    return {
      message:
        "Deletion started. The roster’s deletion operations show active cleanup and backup expiry separately.",
      ok: true,
    };
  }
  if (reply.problem === "deletion-impact-changed")
    return {
      message:
        "The shared-footage impact changed. Close this dialog, reload, and review the new counts.",
    };
  if (reply.problem === "deletion-challenge-mismatch")
    return { message: "Type the displayed deletion phrase exactly." };
  return {
    message:
      "Deletion could not be started. Nothing is being reported as deleted. Try again.",
  };
}
