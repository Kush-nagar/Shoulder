/**
 * Training-plan helpers shared by the coach editor and the player views.
 * Pure: no imports, so the Node test can load it directly.
 */

export const PLAN_MAX_ITEMS = 8;
export const PLAN_NOTE_MAX = 200;
export const PLAN_TITLE_MAX = 80;

/** The Monday (UTC) of the week containing `day`, as yyyy-mm-dd. */
export function mondayOf(day: Date): string {
  const monday = new Date(
    Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate()),
  );
  monday.setUTCDate(monday.getUTCDate() - ((monday.getUTCDay() + 6) % 7));
  return monday.toISOString().slice(0, 10);
}

/** "Week of Sep 21" for a yyyy-mm-dd Monday. */
export function weekLabel(weekOf: string): string {
  const day = new Date(`${weekOf}T00:00:00Z`);
  if (Number.isNaN(day.valueOf())) return "Week";
  return `Week of ${new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(day)}`;
}

export type PlanDraft = {
  title: string;
  week_of: string;
  player_id: string | null;
  items: { drill_slug: string; note: string }[];
};

/**
 * Validates the editor form. `slugs` are the known drill slugs; `players` the
 * coach's roster ids. Rows with no drill chosen are ignored.
 */
export function parsePlanForm(
  form: {
    title: string;
    week: string;
    target: string;
    drills: string[];
    notes: string[];
  },
  slugs: ReadonlySet<string>,
  players: ReadonlySet<string>,
): { ok: true; plan: PlanDraft } | { ok: false; message: string } {
  const title = form.title.trim();
  if (title.length < 1 || title.length > PLAN_TITLE_MAX)
    return { ok: false, message: "Enter a title of 1 to 80 characters." };
  if (!/^\d{4}-\d{2}-\d{2}$/.test(form.week))
    return { ok: false, message: "Choose the week this plan is for." };
  const day = new Date(`${form.week}T00:00:00Z`);
  if (Number.isNaN(day.valueOf()))
    return { ok: false, message: "Choose the week this plan is for." };
  let player_id: string | null = null;
  if (form.target !== "team") {
    if (!players.has(form.target))
      return { ok: false, message: "Choose a player or the whole team." };
    player_id = form.target;
  }
  const items: PlanDraft["items"] = [];
  for (const [index, slug] of form.drills.entries()) {
    if (!slug) continue;
    if (!slugs.has(slug))
      return { ok: false, message: "Choose drills from the library." };
    const note = (form.notes[index] ?? "").trim();
    if (note.length > PLAN_NOTE_MAX)
      return { ok: false, message: "Keep each note to 200 characters." };
    items.push({ drill_slug: slug, note });
  }
  if (items.length < 1 || items.length > PLAN_MAX_ITEMS)
    return { ok: false, message: "Choose 1 to 8 drills." };
  return {
    ok: true,
    plan: { title, week_of: mondayOf(day), player_id, items },
  };
}
