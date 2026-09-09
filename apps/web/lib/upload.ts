/**
 * Pure upload planning for the coach upload screen.
 *
 * No React, no I/O, no browser API. `docs/00-decisions.md` D5 makes the server
 * authoritative for what has actually arrived: everything here decides what to
 * send next given the server's answer, and the locally cached hint is only ever
 * used to recognise the same file again.
 */

/** What the browser remembers between visits. It is a hint, never a claim. */
export type ResumeHint = {
  video_id: string;
  game_id: string;
  /** Display name only; the object key is derived server-side from the id. */
  name: string;
  size: number;
  /** `File.lastModified`, so a different file with the same name is caught. */
  last_modified: number;
};

export type FileIdentity = {
  name: string;
  size: number;
  lastModified: number;
};

export const ALLOWED_EXTENSIONS = ["mp4", "m4v", "mov"] as const;
/** Mirrors `MAX_UPLOAD_BYTES` in `services/api/storage.py`. */
export const MAX_UPLOAD_BYTES = 8 * 1024 * 1024 * 1024;
/** At most three parts in flight, from `docs/02-architecture.md`. */
export const CONCURRENCY = 3;

export function extensionOf(name: string): string {
  const base = name.replace(/\\/g, "/").split("/").pop() ?? "";
  return base.includes(".") ? (base.split(".").pop() ?? "").toLowerCase() : "";
}

/** One plain sentence, or null when the file may be uploaded. */
export function validateFile(file: FileIdentity): string | null {
  if (
    !ALLOWED_EXTENSIONS.includes(
      extensionOf(file.name) as (typeof ALLOWED_EXTENSIONS)[number],
    )
  )
    return "Choose an MP4, M4V, or MOV match file.";
  if (file.size <= 0) return "That file is empty.";
  if (file.size > MAX_UPLOAD_BYTES)
    return `That file is larger than ${formatBytes(MAX_UPLOAD_BYTES)}.`;
  return null;
}

/**
 * Does this file match the upload the hint remembers?
 *
 * Name, exact byte length, and modified time together. Two of the three would
 * accept a re-export of the same match, which would corrupt the object: the
 * remaining parts would come from different bytes than the parts already
 * stored. `docs/11-testing-quality.md` requires that a different file with the
 * same name does not resume the old upload.
 */
export function sameFile(hint: ResumeHint, file: FileIdentity): boolean {
  return (
    hint.name === file.name &&
    hint.size === file.size &&
    hint.last_modified === file.lastModified
  );
}

/**
 * Byte range for one part, given the server's part size.
 *
 * `end` is exclusive, matching `Blob.slice`.
 */
export function partRange(
  partNumber: number,
  partSize: number,
  totalBytes: number,
): { start: number; end: number } {
  const start = (partNumber - 1) * partSize;
  return { start, end: Math.min(start + partSize, totalBytes) };
}

/**
 * Fraction of the file already stored, from the server's confirmed parts.
 *
 * Derived from part numbers rather than a running byte counter, so a reload
 * shows real progress instead of restarting at zero.
 */
export function storedFraction(
  confirmedParts: number[],
  partSize: number,
  totalBytes: number,
): number {
  if (totalBytes <= 0) return 0;
  const stored = confirmedParts.reduce((sum, number) => {
    const { start, end } = partRange(number, partSize, totalBytes);
    return sum + Math.max(0, end - start);
  }, 0);
  return Math.min(1, stored / totalBytes);
}

/** Human byte size for progress copy. Deliberately coarse. */
export function formatBytes(bytes: number): string {
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value >= 10 || unit === 0 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`;
}

/**
 * Run `worker` over every item with at most `limit` in flight.
 *
 * Rejects as soon as one worker rejects, leaving already-started uploads to
 * settle; the caller re-reads the server's state rather than trusting whatever
 * was in flight when it stopped.
 */
export async function inParallel<T>(
  items: T[],
  limit: number,
  worker: (item: T) => Promise<void>,
): Promise<void> {
  const queue = [...items];
  const runners = Array.from(
    { length: Math.min(limit, queue.length) },
    async () => {
      for (let next = queue.shift(); next !== undefined; next = queue.shift())
        await worker(next);
    },
  );
  await Promise.all(runners);
}
