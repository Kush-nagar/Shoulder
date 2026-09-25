"use client";

import { LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { focus, primaryButton, secondaryButton } from "../ui";

const PATH = "/api/player/leaderboard/membership";

async function send(method: "PUT" | "DELETE", body?: object) {
  const response = await fetch(PATH, {
    method,
    cache: "no-store",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  return response.status;
}

/** Join, or change the nickname once joined. */
export function NicknameForm({ current }: { current: string | null }) {
  const router = useRouter();
  const [nickname, setNickname] = useState(current ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const status = await send("PUT", { nickname });
      if (status === 422) {
        setError(
          "Choose a different nickname: 2 to 20 letters, numbers or spaces, with no rude words or contact details.",
        );
      } else if (status >= 400) {
        throw new Error("save");
      } else {
        router.refresh();
      }
    } catch {
      setError("Could not save. Nothing changed. Try again.");
    }
    setSaving(false);
  }

  return (
    <form onSubmit={(event) => void submit(event)} className="max-w-[440px]">
      <label htmlFor="nickname" className="block text-[16px] font-semibold">
        {current ? "Change your nickname" : "Your nickname"}
      </label>
      <p id="nickname-hint" className="mt-1 text-[14px] leading-5 text-muted">
        2 to 20 letters, numbers or spaces. Not your real name.
      </p>
      <div className="mt-2 flex flex-wrap gap-3">
        <input
          id="nickname"
          name="nickname"
          value={nickname}
          onChange={(event) => setNickname(event.target.value)}
          required
          minLength={2}
          maxLength={20}
          pattern="[A-Za-z0-9 ]{2,20}"
          autoComplete="off"
          aria-describedby="nickname-hint"
          aria-invalid={error ? true : undefined}
          className={`min-h-11 min-w-0 flex-1 basis-48 rounded-lg border border-control-border bg-paper px-3 text-[16px] transition-colors duration-150 hover:border-ink-2 ${focus}`}
        />
        <button
          type="submit"
          disabled={saving || nickname.trim() === (current ?? "")}
          className={primaryButton}
        >
          {saving ? "Saving…" : current ? "Save nickname" : "Join the board"}
        </button>
      </div>
      {error ? (
        <p role="alert" className="mt-2 text-[16px] leading-6 text-error">
          {error}
        </p>
      ) : null}
    </form>
  );
}

/** Leave with an inline confirmation that opens on the safe choice. */
export function LeaveBoard() {
  const router = useRouter();
  const stayRef = useRef<HTMLButtonElement>(null);
  const [confirm, setConfirm] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (confirm) stayRef.current?.focus();
  }, [confirm]);

  async function leave() {
    setLeaving(true);
    setError(null);
    try {
      if ((await send("DELETE")) >= 400) throw new Error("leave");
      setConfirm(false);
      router.refresh();
    } catch {
      setError("Could not leave. You are still on the board. Try again.");
    }
    setLeaving(false);
  }

  if (!confirm) {
    return (
      <button
        type="button"
        onClick={() => setConfirm(true)}
        className={`-ml-1 inline-flex min-h-11 items-center gap-2 rounded-lg px-1 text-[16px] font-semibold text-ink-2 underline-offset-4 hover:text-ink hover:underline ${focus}`}
      >
        <LogOut size={18} strokeWidth={2} aria-hidden="true" />
        Leave the board
      </button>
    );
  }
  return (
    <div
      role="alertdialog"
      aria-labelledby="leave-title"
      aria-describedby="leave-body"
      className="max-w-[560px] rounded-xl border border-line-strong bg-surface-subtle p-4 md:p-5"
    >
      <h3 id="leave-title" className="text-[17px] font-semibold text-ink">
        Leave the team board?
      </h3>
      <p id="leave-body" className="mt-1 text-[16px] leading-6 text-ink-2">
        Your nickname and totals disappear from it straight away. Your sessions
        stay yours. You can join again any time.
      </p>
      {error ? (
        <p role="alert" className="mt-2 text-[16px] text-error">
          {error}
        </p>
      ) : null}
      <div className="mt-4 flex flex-wrap gap-3">
        <button
          type="button"
          onClick={() => void leave()}
          disabled={leaving}
          className={secondaryButton}
        >
          <LogOut size={18} strokeWidth={2} aria-hidden="true" />
          {leaving ? "Leaving…" : "Leave"}
        </button>
        <button
          type="button"
          ref={stayRef}
          onClick={() => setConfirm(false)}
          disabled={leaving}
          className={primaryButton}
        >
          Stay on the board
        </button>
      </div>
    </div>
  );
}
