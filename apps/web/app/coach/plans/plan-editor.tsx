"use client";

import { Plus, X } from "lucide-react";
import { useActionState, useEffect, useId, useState } from "react";
import { PLAN_MAX_ITEMS, PLAN_NOTE_MAX } from "../../../lib/plans";
import {
  type ActionState,
  field,
  focus,
  label,
  metadata,
  primary,
  secondary,
} from "../ui";
import { savePlan } from "./actions";

export type DrillOption = { slug: string; title: string; focus: string };
export type PlayerOption = { id: string; name: string };
export type PlanValues = {
  id: string;
  title: string;
  week_of: string;
  player_id: string | null;
  items: { drill_slug: string; note: string }[];
};

type Row = { key: number; drill_slug: string; note: string };

function rowsFrom(items: PlanValues["items"] | undefined): Row[] {
  const source = items?.length ? items : [{ drill_slug: "", note: "" }];
  return source.map((item, key) => ({ key, ...item }));
}

export function PlanEditor({
  drills,
  players,
  thisWeek,
  plan,
  defaultTarget = "team",
}: {
  drills: DrillOption[];
  players: PlayerOption[];
  thisWeek: string;
  plan?: PlanValues;
  defaultTarget?: string;
}) {
  const [state, submit, pending] = useActionState<ActionState, FormData>(
    savePlan,
    { message: "" },
  );
  const [rows, setRows] = useState<Row[]>(() => rowsFrom(plan?.items));
  const [nextKey, setNextKey] = useState(rows.length);
  const id = useId();
  // A saved new plan clears the form for the next one; React resets the
  // uncontrolled fields, the drill rows are reset here.
  useEffect(() => {
    if (state.ok && !plan) setRows(rowsFrom(undefined));
  }, [state, plan]);

  const groups = [...new Set(drills.map((drill) => drill.focus))];
  const target = plan ? (plan.player_id ?? "team") : defaultTarget;

  return (
    <form action={submit} className="space-y-5">
      {plan ? <input type="hidden" name="plan_id" value={plan.id} /> : null}
      <div className="grid gap-4 md:grid-cols-[minmax(0,1.6fr)_minmax(9.5rem,1fr)_minmax(0,1.2fr)]">
        <div>
          <label htmlFor={`${id}-title`} className={label}>
            Title (required)
          </label>
          <input
            id={`${id}-title`}
            name="title"
            required
            maxLength={80}
            defaultValue={plan?.title}
            placeholder="Scanning week"
            className={`${field} mt-1`}
          />
        </div>
        <div>
          <label htmlFor={`${id}-week`} className={label}>
            Week of
          </label>
          <input
            id={`${id}-week`}
            name="week_of"
            type="date"
            required
            defaultValue={plan?.week_of ?? thisWeek}
            className={`${field} mt-1`}
          />
        </div>
        <div>
          <label htmlFor={`${id}-target`} className={label}>
            For
          </label>
          {/* The target is fixed once a plan exists. */}
          {plan ? <input type="hidden" name="target" value={target} /> : null}
          <select
            id={`${id}-target`}
            name={plan ? undefined : "target"}
            defaultValue={target}
            disabled={Boolean(plan)}
            className={`${field} mt-1 disabled:opacity-70`}
          >
            <option value="team">Whole team</option>
            {players.map((player) => (
              <option key={player.id} value={player.id}>
                {player.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      <fieldset>
        <legend className={label}>
          Drills ({rows.length} of {PLAN_MAX_ITEMS})
        </legend>
        <ol className="mt-2 space-y-3">
          {rows.map((row, index) => (
            <li
              key={row.key}
              className="grid gap-2 rounded-lg border border-line bg-paper p-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)_auto] md:items-end"
            >
              <div>
                <label htmlFor={`${id}-drill-${row.key}`} className={metadata}>
                  Drill {index + 1}
                </label>
                <select
                  id={`${id}-drill-${row.key}`}
                  name="drill_slug"
                  required
                  defaultValue={row.drill_slug}
                  className={`${field} mt-1`}
                >
                  <option value="">Choose a drill</option>
                  {groups.map((group) => (
                    <optgroup key={group} label={group}>
                      {drills
                        .filter((drill) => drill.focus === group)
                        .map((drill) => (
                          <option key={drill.slug} value={drill.slug}>
                            {drill.title}
                          </option>
                        ))}
                    </optgroup>
                  ))}
                </select>
              </div>
              <div>
                <label htmlFor={`${id}-note-${row.key}`} className={metadata}>
                  Note for drill {index + 1}
                </label>
                <input
                  id={`${id}-note-${row.key}`}
                  name="note"
                  maxLength={PLAN_NOTE_MAX}
                  defaultValue={row.note}
                  placeholder="What to focus on"
                  className={`${field} mt-1`}
                />
              </div>
              <button
                type="button"
                disabled={rows.length === 1}
                onClick={() =>
                  setRows((current) =>
                    current.filter((item) => item.key !== row.key),
                  )
                }
                aria-label={`Remove drill ${index + 1}`}
                className={`inline-flex size-10 items-center justify-center justify-self-end rounded-lg text-muted hover:bg-surface-subtle hover:text-ink disabled:opacity-40 ${focus}`}
              >
                <X size={18} strokeWidth={2} aria-hidden="true" />
              </button>
            </li>
          ))}
        </ol>
        <button
          type="button"
          disabled={rows.length >= PLAN_MAX_ITEMS}
          onClick={() => {
            setRows((current) => [
              ...current,
              { key: nextKey, drill_slug: "", note: "" },
            ]);
            setNextKey((key) => key + 1);
          }}
          className={`${secondary} mt-3`}
        >
          <Plus size={18} strokeWidth={2} aria-hidden="true" />
          Add a drill
        </button>
      </fieldset>

      <div className="flex flex-wrap items-center gap-4">
        <button type="submit" disabled={pending} className={primary}>
          {pending ? "Saving…" : plan ? "Save changes" : "Save plan"}
        </button>
        <p
          role={state.ok ? "status" : state.message ? "alert" : undefined}
          className={`text-[15px] ${state.ok ? "text-ink" : "text-error"}`}
        >
          {state.message}
        </p>
      </div>
    </form>
  );
}
