"use client";

import { useActionState, useEffect, useId, useRef } from "react";
import type { PlayerErasureImpact } from "../../../../lib/api";
import {
  componentTitle,
  destructive,
  dialog,
  field,
  label,
  metadata,
  primary,
  secondary,
} from "../../ui";
import { erasePlayerData } from "./actions";

export function ErasePlayer({
  name,
  impact,
  idempotencyKey,
}: {
  name: string;
  impact: PlayerErasureImpact;
  idempotencyKey: string;
}) {
  const [state, submit, pending] = useActionState(erasePlayerData, {
    message: "",
  });
  const box = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const challengeId = useId();

  useEffect(() => {
    if (state.ok) box.current?.close();
  }, [state]);

  return (
    <section
      className="mt-8 max-w-170 border-t border-line pt-5"
      aria-labelledby={`${titleId}-section`}
    >
      <h2 id={`${titleId}-section`} className={componentTitle}>
        Permanent deletion
      </h2>
      <p className="mt-2 text-[15px] leading-[1.5] text-muted">
        Shared match footage cannot be separated by player. This operation is
        broader than archiving and cannot be undone.
      </p>
      {impact.can_request && !state.ok ? (
        <button
          type="button"
          onClick={() => box.current?.showModal()}
          className={`${destructive} mt-3`}
        >
          Permanently delete {name}’s data
        </button>
      ) : (
        <p className={`${metadata} mt-3`}>
          Deletion is already pending for this player.
        </p>
      )}
      {state.message ? (
        <p
          role={state.ok ? "status" : "alert"}
          className="mt-3 text-[15px] font-medium"
        >
          {state.message}
        </p>
      ) : null}
      {impact.can_request && !state.ok ? (
        <dialog ref={box} aria-labelledby={titleId} className={dialog}>
          <form action={submit} className="p-5">
            <h2 id={titleId} className={componentTitle}>
              Permanently delete {name}’s data?
            </h2>
            <p className="mt-3 text-[15px] leading-[1.5]">
              This deletes {impact.video_count} team videos and{" "}
              {impact.other_player_clip_count} clips published for other
              players, plus video-dependent judgments, revisions, and
              reflections.
            </p>
            <p className="mt-3 text-[15px] leading-[1.5]">
              It preserves {impact.remaining_player_count} other player rows,{" "}
              {impact.remaining_goal_count} goals, and{" "}
              {impact.remaining_linked_account_count} linked player accounts.
              External research copies must be reviewed separately.
            </p>
            <input type="hidden" name="player_id" value={impact.player_id} />
            <input
              type="hidden"
              name="idempotency_key"
              value={idempotencyKey}
            />
            <input
              type="hidden"
              name="expected_video_count"
              value={impact.video_count}
            />
            <input
              type="hidden"
              name="expected_other_player_clip_count"
              value={impact.other_player_clip_count}
            />
            <label className="mt-4 flex items-start gap-3 text-[15px] leading-[1.5]">
              <input
                name="collateral_deletion_confirmed"
                type="checkbox"
                required
                className="mt-1"
              />
              <span>
                I confirm deletion of the shared videos and every player’s
                affected clips.
              </span>
            </label>
            <label className="mt-3 flex items-start gap-3 text-[15px] leading-[1.5]">
              <input
                name="notice_confirmed"
                type="checkbox"
                required
                className="mt-1"
              />
              <span>
                I have completed the required player or guardian notice.
              </span>
            </label>
            <label className="mt-3 flex items-start gap-3 text-[15px] leading-[1.5]">
              <input
                name="unrelated_data_reviewed"
                type="checkbox"
                required
                className="mt-1"
              />
              <span>
                I reviewed unrelated goals and account associations and
                confirmed what must remain.
              </span>
            </label>
            <label htmlFor={challengeId} className={`${label} mt-4`}>
              Type this phrase exactly: {impact.challenge}
            </label>
            <input
              id={challengeId}
              name="challenge"
              required
              autoComplete="off"
              spellCheck={false}
              className={`${field} mt-1 font-mono`}
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
                {pending ? "Starting deletion…" : "Start permanent deletion"}
              </button>
            </div>
            {state.message && !state.ok ? (
              <p role="alert" className="mt-3 text-[15px] font-medium">
                {state.message}
              </p>
            ) : (
              <p className={`${metadata} mt-3`}>
                Nothing changes until every confirmation is complete.
              </p>
            )}
          </form>
        </dialog>
      ) : null}
    </section>
  );
}
