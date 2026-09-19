/** Pure keyboard and boundary decisions shared by the review UI and unit tests. */

type TextEntryTarget = {
  tagName: string;
  isContentEditable: boolean;
};

export type ReviewShortcut =
  | { type: "toggle-playback" }
  | { type: "seek"; seconds: number }
  | { type: "mark-in" }
  | { type: "mark-out" }
  | {
      type: "select-verdict";
      verdict: "applied" | "opportunity" | "not_relevant";
    }
  | { type: "focus-comment" }
  | { type: "save-draft" }
  | { type: "focus-video" };

export function isTextEntryTarget(target: TextEntryTarget | null): boolean {
  return Boolean(
    target &&
      (target.isContentEditable ||
        ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)),
  );
}

export function reviewShortcut(
  key: string,
  shiftKey: boolean,
  editingText: boolean,
): ReviewShortcut | null {
  if (key === "Enter") return { type: "save-draft" };
  if (editingText) {
    return key === "Escape" ? { type: "focus-video" } : null;
  }
  switch (key) {
    case " ":
    case "k":
    case "K":
      return { type: "toggle-playback" };
    case "ArrowLeft":
      return { type: "seek", seconds: shiftKey ? -10 : -1 };
    case "ArrowRight":
      return { type: "seek", seconds: shiftKey ? 10 : 1 };
    case "j":
    case "J":
      return { type: "seek", seconds: -10 };
    case "l":
    case "L":
      return { type: "seek", seconds: 10 };
    case "i":
    case "I":
      return { type: "mark-in" };
    case "o":
    case "O":
      return { type: "mark-out" };
    case "1":
      return { type: "select-verdict", verdict: "applied" };
    case "2":
      return { type: "select-verdict", verdict: "opportunity" };
    case "3":
      return { type: "select-verdict", verdict: "not_relevant" };
    case "c":
    case "C":
      return { type: "focus-comment" };
    case "Escape":
      return { type: "focus-video" };
    default:
      return null;
  }
}

export function validClipBounds(
  startMs: number,
  endMs: number,
  durationMs: number,
): boolean {
  return (
    Number.isInteger(startMs) &&
    Number.isInteger(endMs) &&
    Number.isInteger(durationMs) &&
    startMs >= 0 &&
    endMs > startMs &&
    endMs <= durationMs
  );
}
