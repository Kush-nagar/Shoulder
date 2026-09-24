"use client";

import { LogOut } from "lucide-react";
import { clearAllReflectionDrafts } from "../../lib/reflection-drafts";
import { focus } from "./ui";

export function PlayerSignOutForm({ className = "" }: { className?: string }) {
  return (
    <form
      action="/auth/sign-out"
      method="post"
      onSubmit={() => clearAllReflectionDrafts(window.localStorage)}
    >
      <button
        type="submit"
        className={`flex min-h-11 w-full items-center gap-3 rounded-lg px-3 text-left text-[16px] hover:bg-surface-subtle ${focus} ${className}`}
      >
        <LogOut size={20} strokeWidth={2} aria-hidden="true" />
        Sign out
      </button>
    </form>
  );
}
