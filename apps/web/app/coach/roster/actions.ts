"use server";

import { revalidatePath } from "next/cache";
import {
  apiWrite,
  type BulkResult,
  type DeletionStatus,
  fetchTeams,
  type InviteResult,
  type RetentionStatus,
  type RosterPlayer,
} from "../../../lib/api";
import { parseRoster } from "../../../lib/roster";
import { requireCoach } from "../session";
import type { ActionState } from "../ui";

/** Plain operational copy. No provider name, status code, SQL, or email. */
function failure(status: number, conflict: string): string {
  if (status === 409) return conflict;
  if (status === 422) return "Check the fields below. Nothing was saved.";
  if (status === 401 || status === 403 || status === 404)
    return "You can no longer change this roster. Nothing was saved. Reload the page.";
  return "Could not save. Nothing was saved and your entry was kept. Try again.";
}

async function team(token: string) {
  // One team per workspace: the roster is resolved server-side, never posted.
  // Undefined covers both "no team" and a failed lookup; callers say so plainly
  // rather than claiming the coach has no team.
  return (await fetchTeams(token))?.[0];
}

function optional(form: FormData, name: string): string | null {
  const value = String(form.get(name) ?? "").trim();
  return value === "" ? null : value;
}

function jersey(form: FormData): number | null | undefined {
  const raw = String(form.get("jersey_number") ?? "").trim();
  if (raw === "") return null;
  return /^\d{1,2}$/.test(raw) ? Number(raw) : undefined;
}

export async function addPlayer(
  _previous: ActionState,
  form: FormData,
): Promise<ActionState> {
  const token = await requireCoach();
  const current = await team(token);
  if (!current) return { message: "No team is set up yet." };
  const display_name = String(form.get("display_name") ?? "").trim();
  if (display_name.length < 1 || display_name.length > 80)
    return { message: "Enter a name of 1 to 80 characters." };
  const jersey_number = jersey(form);
  if (jersey_number === undefined)
    return { message: "Number must be a whole number from 0 to 99." };
  const reply = await apiWrite<RosterPlayer>(
    token,
    `/v1/teams/${current.team_id}/players`,
    "POST",
    { display_name, jersey_number, position: optional(form, "position") },
  );
  if (reply.status === 201) {
    revalidatePath("/coach/roster");
    return { message: `${display_name} was added.`, ok: true };
  }
  return {
    message: failure(
      reply.status,
      "That number is already used on this roster. Nothing was saved.",
    ),
  };
}

export async function saveRoster(
  _previous: ActionState,
  form: FormData,
): Promise<ActionState> {
  const token = await requireCoach();
  const current = await team(token);
  if (!current) return { message: "No team is set up yet." };
  const rows = parseRoster(String(form.get("paste") ?? ""));
  if (rows.length === 0) return { message: "Paste at least one row." };
  if (rows.length > 40)
    return { message: "Paste at most 40 rows at a time. Nothing was saved." };
  if (rows.some((row) => row.errors.length > 0))
    return {
      message:
        "Fix the rows listed below. Nothing was saved and your paste was kept.",
    };
  const reply = await apiWrite<BulkResult>(
    token,
    `/v1/teams/${current.team_id}/players/bulk`,
    "POST",
    {
      commit: true,
      rows: rows.map(({ display_name, jersey_number, position }) => ({
        display_name,
        jersey_number,
        position,
      })),
    },
  );
  if (reply.status === 201) {
    revalidatePath("/coach/roster");
    return {
      message: `${rows.length} ${rows.length === 1 ? "player was" : "players were"} added.`,
      ok: true,
    };
  }
  return {
    message: failure(
      reply.status,
      "A number is already used on this roster. Nothing was saved and your paste was kept.",
    ),
  };
}

export async function archivePlayer(
  _previous: ActionState,
  form: FormData,
): Promise<ActionState> {
  const token = await requireCoach();
  const id = String(form.get("player_id") ?? "");
  const reply = await apiWrite(token, `/v1/players/${id}/archive`, "POST", {});
  if (reply.status >= 200 && reply.status < 300) {
    revalidatePath("/coach/roster");
    return { message: "Player archived.", ok: true };
  }
  return {
    message: failure(
      reply.status,
      "That player is already archived. Nothing was changed.",
    ),
  };
}

export async function invitePlayer(
  _previous: ActionState,
  form: FormData,
): Promise<ActionState> {
  const token = await requireCoach();
  const id = String(form.get("player_id") ?? "");
  const email = String(form.get("email") ?? "").trim();
  if (!email) return { message: "Enter the email address to link." };
  const reply = await apiWrite<InviteResult>(
    token,
    `/v1/players/${id}/invite`,
    "POST",
    { email },
  );
  if (reply.status >= 200 && reply.status < 300) {
    revalidatePath("/coach/roster");
    revalidatePath(`/coach/players/${id}`);
    return { message: "Account linked. No message was sent yet.", ok: true };
  }
  // ADR 0017: the ordinary failure is an address that has never signed in, not
  // a malformed one. Saying "not usable" for that would send a coach hunting a
  // typo that is not there.
  if (reply.problem === "invitation-account-not-found")
    return {
      message:
        "That person has not signed in to Shoulder yet, so there is no account" +
        " to link. Nothing was saved.",
    };
  if (reply.problem === "player-off-roster")
    return {
      message:
        "That player is off the roster, so an account cannot be linked to them.",
    };
  if (reply.status === 422)
    return { message: "That email address is not usable. Nothing was saved." };
  return {
    message: failure(
      reply.status,
      "This player is already linked to an account. Nothing was changed.",
    ),
  };
}

export async function confirmRetention(
  _previous: ActionState,
  form: FormData,
): Promise<ActionState> {
  const token = await requireCoach();
  const current = await team(token);
  if (!current) return { message: "No team is set up yet." };
  const backupDays = Number(String(form.get("provider_backup_max_days") ?? ""));
  if (!Number.isInteger(backupDays) || backupDays < 1 || backupDays > 30)
    return {
      message:
        "Enter the provider’s confirmed backup maximum, from 1 to 30 days.",
    };
  const confirmations = {
    season_cutoff_confirmed: form.get("season_cutoff_confirmed") === "on",
    provider_backup_expiry_confirmed:
      form.get("provider_backup_expiry_confirmed") === "on",
    notice_confirmed: form.get("notice_confirmed") === "on",
    collateral_deletion_confirmed:
      form.get("collateral_deletion_confirmed") === "on",
    operator_confirmed: form.get("operator_confirmed") === "on",
  };
  if (!Object.values(confirmations).every(Boolean))
    return {
      message: "Confirm every operational requirement before continuing.",
    };
  const reply = await apiWrite<RetentionStatus>(
    token,
    `/v1/teams/${current.team_id}/retention-confirmation`,
    "POST",
    { provider_backup_max_days: backupDays, ...confirmations },
  );
  if (reply.status === 200) {
    revalidatePath("/coach/roster");
    revalidatePath("/coach/upload");
    return { message: "Retention and deletion setup confirmed.", ok: true };
  }
  return {
    message:
      reply.status === 422
        ? "Check every confirmation and the backup maximum. Nothing was saved."
        : "Could not confirm the setup. Nothing was saved. Try again.",
  };
}

export async function confirmBackupExpiry(
  _previous: ActionState,
  form: FormData,
): Promise<ActionState> {
  const token = await requireCoach();
  const manifestId = String(form.get("manifest_id") ?? "");
  const reply = await apiWrite<DeletionStatus>(
    token,
    `/v1/deletions/${manifestId}/backup-expired`,
    "POST",
    {},
  );
  if (reply.status === 200) {
    revalidatePath("/coach/roster");
    return {
      message: "Backup expiry confirmed; deletion is complete.",
      ok: true,
    };
  }
  return {
    message:
      reply.problem === "backup-not-expired"
        ? "The provider’s confirmed backup deadline has not arrived yet."
        : "Could not confirm backup expiry. Nothing was changed.",
  };
}
