"use client";

import { useActionState, useEffect, useId, useRef } from "react";
import { invitePlayer } from "../../roster/actions";
import {
  componentTitle,
  dialog,
  field,
  label,
  metadata,
  primary,
  secondary,
  tertiary,
} from "../../ui";

/** Optional and last: the whole roster works before any email is collected. */
export function InvitePlayer({
  playerId,
  name,
}: {
  playerId: string;
  name: string;
}) {
  const [state, submit, pending] = useActionState(invitePlayer, {
    message: "",
  });
  const box = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const emailId = useId();
  const helpId = useId();

  useEffect(() => {
    if (state.ok) box.current?.close();
  }, [state]);

  return (
    <>
      <button
        type="button"
        aria-label={`Link an account for ${name}`}
        onClick={() => box.current?.showModal()}
        className={tertiary}
      >
        Link an account
      </button>
      <dialog ref={box} aria-labelledby={titleId} className={dialog}>
        <form action={submit} className="p-5">
          <h2 id={titleId} className={componentTitle}>
            Link an account for {name}
          </h2>
          <p id={helpId} className="mt-3 text-[15px] leading-[1.5]">
            This connects {name} to an account so they can sign in later. No
            message is sent yet, and this is not required to keep using the
            roster.
          </p>
          <input type="hidden" name="player_id" value={playerId} />
          <label htmlFor={emailId} className={`${label} mt-4`}>
            Email address
          </label>
          <input
            id={emailId}
            name="email"
            type="email"
            required
            maxLength={254}
            autoComplete="off"
            aria-describedby={helpId}
            className={`${field} mt-1`}
          />
          <div className="mt-5 flex flex-wrap justify-end gap-3">
            <button
              type="button"
              onClick={() => box.current?.close()}
              className={secondary}
            >
              Cancel
            </button>
            <button type="submit" disabled={pending} className={primary}>
              {pending ? "Linking…" : "Link account"}
            </button>
          </div>
          {state.message && !state.ok ? (
            <p role="alert" className="mt-3 text-[15px] font-medium">
              {state.message}
            </p>
          ) : (
            <p className={`${metadata} mt-3`}>
              The address is used only to connect the account.
            </p>
          )}
        </form>
      </dialog>
    </>
  );
}
