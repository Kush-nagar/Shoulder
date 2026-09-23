export const focus =
  "outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

export const primaryButton = `inline-flex min-h-11 items-center justify-center rounded-lg bg-action px-5 text-[16px] font-semibold text-white transition-[background-color,transform] duration-150 ease-out hover:bg-action-hover active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-45 ${focus}`;

export const secondaryButton = `inline-flex min-h-11 items-center justify-center rounded-lg border border-line-strong px-4 text-[16px] font-semibold transition-[background-color,transform] duration-150 ease-out hover:bg-surface-subtle active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-45 ${focus}`;

export function practiceDate(value: string) {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(value));
}

export function clock(ms: number | null) {
  if (ms === null) return null;
  const seconds = Math.round(ms / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

export function practiceTitle(title: string | null) {
  return title?.trim() || "Practice video";
}
