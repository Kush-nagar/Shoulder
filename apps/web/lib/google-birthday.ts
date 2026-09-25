/** Scope for the optional `/coaching` age check; never on the main sign-in. */
export const BIRTHDAY_SCOPE =
  "https://www.googleapis.com/auth/user.birthday.read";

type Birthday = {
  metadata?: { primary?: unknown };
  date?: { year?: unknown };
};

/**
 * Birth year from a People API `people/me?personFields=birthdays` body, or
 * null. Prefers the primary entry; entries without a plausible year are
 * skipped. Only the year ever leaves this function.
 */
export function birthYearFrom(body: unknown, now = new Date()): number | null {
  const list = (body as { birthdays?: unknown } | null)?.birthdays;
  if (!Array.isArray(list)) return null;
  const valid = (list as Birthday[]).filter((entry) => {
    const year = entry?.date?.year;
    return (
      Number.isInteger(year) &&
      (year as number) >= 1900 &&
      (year as number) <= now.getUTCFullYear()
    );
  });
  const chosen =
    valid.find((entry) => entry.metadata?.primary === true) ?? valid[0];
  return chosen ? (chosen.date?.year as number) : null;
}
