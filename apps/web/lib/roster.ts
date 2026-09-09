/**
 * Pure preview parser for pasted `name, number, position` roster rows.
 * No React and no I/O: the server re-validates every row and stays authoritative.
 */

export type ParsedRow = {
  display_name: string;
  jersey_number: number | null;
  position: string | null;
  errors: string[];
};

export const NAME_MAX = 80;
export const POSITION_MAX = 40;

export function parseRoster(text: string): ParsedRow[] {
  const rows: ParsedRow[] = [];
  for (const line of text.split(/\r?\n/)) {
    // A blank line is spacing in a paste, not a player.
    if (!line.trim()) continue;
    const fields = line.split(",").map((field) => field.trim());
    // A trailing comma means "no position", not a fourth field.
    while (fields.length > 1 && fields[fields.length - 1] === "") fields.pop();
    const [name = "", number = "", position = ""] = fields;
    const errors: string[] = [];
    if (fields.length > 3) errors.push("Use name, number, position.");
    if (name.length < 1 || name.length > NAME_MAX)
      errors.push(`Name must be 1 to ${NAME_MAX} characters.`);
    let jersey: number | null = null;
    if (number !== "") {
      if (/^\d{1,2}$/.test(number)) jersey = Number(number);
      else errors.push("Number must be a whole number from 0 to 99.");
    }
    if (position.length > POSITION_MAX)
      errors.push(`Position must be ${POSITION_MAX} characters or fewer.`);
    rows.push({
      display_name: name,
      jersey_number: jersey,
      position: position === "" ? null : position,
      errors,
    });
  }
  const counts = new Map<number, number>();
  for (const row of rows)
    if (row.jersey_number !== null)
      counts.set(row.jersey_number, (counts.get(row.jersey_number) ?? 0) + 1);
  // Flag every row of a duplicate pair so the preview names both offenders.
  for (const row of rows)
    if (row.jersey_number !== null && (counts.get(row.jersey_number) ?? 0) > 1)
      row.errors.push("Number is used more than once in this paste.");
  return rows;
}
