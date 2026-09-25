"use client";

import { useActionState } from "react";
import { destructive } from "../ui";
import { deletePlan } from "./actions";

export function DeletePlan({
  planId,
  title,
}: {
  planId: string;
  title: string;
}) {
  const [state, submit, pending] = useActionState(deletePlan, { message: "" });
  return (
    <form
      action={submit}
      onSubmit={(event) => {
        if (!window.confirm(`Remove “${title}”? Players stop seeing it.`))
          event.preventDefault();
      }}
      className="flex min-h-10 items-center gap-3"
    >
      <input type="hidden" name="plan_id" value={planId} />
      <button type="submit" disabled={pending} className={destructive}>
        Remove plan<span className="sr-only">: {title}</span>
      </button>
      {state.message && !state.ok ? (
        <p role="alert" className="text-[15px] text-error">
          {state.message}
        </p>
      ) : null}
    </form>
  );
}
