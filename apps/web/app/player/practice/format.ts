export { focus, primaryButton, secondaryButton } from "../ui";

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

export function monthLabel(value: string) {
  return new Intl.DateTimeFormat("en-US", {
    month: "long",
    year: "numeric",
  }).format(new Date(value));
}

export type PracticeStatus = "Uploading" | "Ready" | "Analysed";

/** Status words for a practice video; "Analysed" once ideas exist. */
export function practiceStatus(
  status: string,
  analysed = false,
): PracticeStatus {
  if (status === "uploading") return "Uploading";
  return analysed ? "Analysed" : "Ready";
}
