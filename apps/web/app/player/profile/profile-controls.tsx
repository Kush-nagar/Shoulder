"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { focus, textLink } from "../ui";

export type ThemeChoice = "system" | "light" | "dark";

const options = [
  { value: "system", label: "System", Icon: Monitor },
  { value: "light", label: "Light", Icon: Sun },
  { value: "dark", label: "Dark", Icon: Moon },
] as const;

/** Writes `sh-theme` so the root layout script applies it before paint. */
export function ThemePicker({ initial }: { initial: ThemeChoice }) {
  const [choice, setChoice] = useState<ThemeChoice>(initial);
  function pick(value: ThemeChoice) {
    setChoice(value);
    const root = document.querySelector<HTMLElement>(".sh-themed");
    if (value === "system") {
      // biome-ignore lint/suspicious/noDocumentCookie: Cookie Store API is missing in Safari and Firefox; this cookie is a non-sensitive preference.
      document.cookie = "sh-theme=; path=/; max-age=0; samesite=lax";
      if (root) delete root.dataset.theme;
    } else {
      // biome-ignore lint/suspicious/noDocumentCookie: as above.
      document.cookie = `sh-theme=${value}; path=/; max-age=31536000; samesite=lax`;
      if (root) root.dataset.theme = value;
    }
  }
  return (
    <fieldset>
      <legend className="text-[16px] font-semibold">Theme</legend>
      <div className="mt-3 grid grid-cols-3 gap-2 sm:max-w-md">
        {options.map(({ value, label, Icon }) => (
          <label
            key={value}
            className={`flex min-h-12 cursor-pointer items-center justify-center gap-2 rounded-lg border text-[15px] font-semibold transition-colors duration-150 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-focus ${
              choice === value
                ? "border-ink bg-ink text-paper"
                : "border-control-border text-ink-2 hover:bg-surface-subtle"
            }`}
          >
            <input
              type="radio"
              name="theme"
              value={value}
              checked={choice === value}
              onChange={() => pick(value)}
              className="sr-only"
            />
            <Icon size={18} strokeWidth={2} aria-hidden="true" />
            {label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

/** Brings the Home guide back by clearing its dismiss flag. */
export function ShowGuideButton() {
  const router = useRouter();
  return (
    <button
      type="button"
      className={`${textLink} ${focus}`}
      onClick={() => {
        try {
          window.localStorage.removeItem("sh.guide.hidden");
        } catch {
          // Storage blocked: the guide already always shows.
        }
        router.push("/player#how-it-works");
      }}
    >
      How Shoulder works
    </button>
  );
}
