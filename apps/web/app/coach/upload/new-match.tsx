"use client";

import { useActionState, useId } from "react";
import {
  componentTitle,
  field,
  label,
  metadata,
  panel,
  secondary,
} from "../ui";
import { createGame } from "./actions";

/** Add one match, then go straight to its upload step. */
export function NewMatchForm() {
  const [state, submit, pending] = useActionState(createGame, { message: "" });
  const ids = { date: useId(), opponent: useId(), kind: useId() };

  return (
    <form
      action={submit}
      className={`${panel} p-5`}
      aria-labelledby={`${ids.date}-heading`}
    >
      <h2 id={`${ids.date}-heading`} className={componentTitle}>
        Add a match
      </h2>
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <div className="w-44">
          <label htmlFor={ids.date} className={label}>
            Date (required)
          </label>
          <input
            id={ids.date}
            name="played_on"
            type="date"
            required
            className={`${field} mt-1`}
          />
        </div>
        <div className="min-w-56 flex-1">
          <label htmlFor={ids.opponent} className={label}>
            Opponent
          </label>
          <input
            id={ids.opponent}
            name="opponent"
            type="text"
            maxLength={100}
            autoComplete="off"
            className={`${field} mt-1`}
          />
        </div>
        <div className="w-40">
          <label htmlFor={ids.kind} className={label}>
            Kind
          </label>
          <select id={ids.kind} name="kind" className={`${field} mt-1`}>
            <option value="match">Match</option>
            <option value="scrimmage">Scrimmage</option>
          </select>
        </div>
        <button type="submit" disabled={pending} className={secondary}>
          {pending ? "Adding…" : "Add match"}
        </button>
      </div>
      <p aria-live="polite" className={`${metadata} mt-2`}>
        {state.message}
      </p>
    </form>
  );
}
