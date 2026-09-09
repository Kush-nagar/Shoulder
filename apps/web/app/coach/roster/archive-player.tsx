"use client";

import { useActionState, useEffect, useId, useRef } from "react";
import {
  componentTitle,
  destructive,
  dialog,
  metadata,
  primary,
  secondary,
} from "../ui";
import { archivePlayer } from "./actions";

/**
 * NOTE: one dialog per row keeps the table a server component. Lift to a
 * single shared dialog if a roster ever grows past a few hundred rows.
 */
export function ArchivePlayer({
  playerId,
  name,
}: {
  playerId: string;
  name: string;
}) {
  const [state, submit, pending] = useActionState(archivePlayer, {
    message: "",
  });
  const box = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    if (state.ok) box.current?.close();
  }, [state]);

  return (
    <>
      <button
        type="button"
        aria-label={`Archive ${name}`}
        onClick={() => box.current?.showModal()}
        className={destructive}
      >
        Archive
      </button>
      <dialog ref={box} aria-labelledby={titleId} className={dialog}>
        <form action={submit} className="p-5">
          <h2 id={titleId} className={componentTitle}>
            Archive {name}?
          </h2>
          <p className="mt-3 text-[15px] leading-[1.5]">
            They come off the roster. Their goals and anything already published
            are kept. This is not deletion.
          </p>
          <input type="hidden" name="player_id" value={playerId} />
          <div className="mt-5 flex flex-wrap justify-end gap-3">
            <button
              type="button"
              onClick={() => box.current?.close()}
              className={secondary}
            >
              Keep on roster
            </button>
            <button type="submit" disabled={pending} className={primary}>
              {pending ? "Archiving…" : "Archive player"}
            </button>
          </div>
          {state.message && !state.ok ? (
            <p role="alert" className="mt-3 text-[15px] font-medium">
              {state.message}
            </p>
          ) : (
            <p className={`${metadata} mt-3`}>
              Nothing changes until you confirm.
            </p>
          )}
        </form>
      </dialog>
    </>
  );
}
