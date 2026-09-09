"use client";

import { useActionState, useEffect, useId, useRef } from "react";
import { componentTitle, field, label, metadata, secondary } from "../ui";
import { addPlayer } from "./actions";

/** The inline add row: one player, without leaving the roster. */
export function AddPlayer() {
  const [state, submit, pending] = useActionState(addPlayer, { message: "" });
  const form = useRef<HTMLFormElement>(null);
  const name = useRef<HTMLInputElement>(null);
  const ids = { name: useId(), number: useId(), position: useId() };

  useEffect(() => {
    if (!state.ok) return;
    form.current?.reset();
    name.current?.focus();
  }, [state]);

  return (
    <form
      ref={form}
      action={submit}
      className="mt-4 border-t border-line pt-4"
      aria-labelledby={`${ids.name}-heading`}
    >
      <h2 id={`${ids.name}-heading`} className={componentTitle}>
        Add one player
      </h2>
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <div className="min-w-56 flex-1">
          <label htmlFor={ids.name} className={label}>
            Name (required)
          </label>
          <input
            ref={name}
            id={ids.name}
            name="display_name"
            type="text"
            required
            maxLength={80}
            autoComplete="off"
            className={`${field} mt-1`}
          />
        </div>
        <div className="w-24">
          <label htmlFor={ids.number} className={label}>
            Number
          </label>
          <input
            id={ids.number}
            name="jersey_number"
            type="text"
            inputMode="numeric"
            pattern="\d{1,2}"
            maxLength={2}
            autoComplete="off"
            className={`${field} mt-1 tabular-nums`}
          />
        </div>
        <div className="w-40">
          <label htmlFor={ids.position} className={label}>
            Position
          </label>
          <input
            id={ids.position}
            name="position"
            type="text"
            maxLength={40}
            autoComplete="off"
            className={`${field} mt-1`}
          />
        </div>
        <button type="submit" disabled={pending} className={secondary}>
          {pending ? "Adding…" : "Add player"}
        </button>
      </div>
      <p className={`${metadata} mt-2`}>
        No email address is needed to add a player.
      </p>
      {state.message ? (
        <p
          role={state.ok ? "status" : "alert"}
          className="mt-2 text-[15px] font-medium"
        >
          {state.message}
        </p>
      ) : null}
    </form>
  );
}
