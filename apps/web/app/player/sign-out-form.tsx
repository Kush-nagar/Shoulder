"use client";

import { clearAllReflectionDrafts } from "../../lib/reflection-drafts";

const focus =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

export function PlayerSignOutForm() {
  return (
    <form
      action="/auth/sign-out"
      method="post"
      onSubmit={() => clearAllReflectionDrafts(window.localStorage)}
    >
      <button
        type="submit"
        className={`min-h-11 w-full rounded-lg px-3 text-left text-[16px] hover:bg-surface-subtle ${focus}`}
      >
        Sign out
      </button>
    </form>
  );
}
