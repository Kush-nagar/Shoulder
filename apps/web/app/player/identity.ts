/**
 * A first name only when the display name plainly is one; account defaults
 * such as an email prefix with digits fall back to neutral copy (docs/09).
 */
export function firstName(displayName: string | null | undefined) {
  const token = displayName?.trim().split(/\s+/)[0] ?? "";
  return /^\p{L}[\p{L}'’-]{0,23}$/u.test(token) ? token : null;
}

export function initial(displayName: string | null | undefined) {
  return (
    (firstName(displayName) ?? displayName ?? "")
      .trim()
      .charAt(0)
      .toUpperCase() || "?"
  );
}
