import assert from "node:assert/strict";
import test from "node:test";
import {
  extensionOf,
  formatBytes,
  inParallel,
  MAX_UPLOAD_BYTES,
  partRange,
  sameFile,
  storedFraction,
  validateFile,
} from "../apps/web/lib/upload.ts";

const PART = 32 * 1024 * 1024;
const file = (over = {}) => ({
  name: "match.mp4",
  size: PART + 1000,
  lastModified: 1_700_000_000_000,
  ...over,
});

test("only the documented container extensions are accepted", () => {
  for (const name of ["match.mp4", "match.MOV", "a.b.m4v"])
    assert.equal(validateFile(file({ name })), null);
  for (const name of ["match.mkv", "match.exe", "match", "match.mp4.txt"])
    assert.match(validateFile(file({ name })), /MP4, M4V, or MOV/);
});

test("an extension is read from the base name, never from a path", () => {
  assert.equal(extensionOf("C:\\Users\\coach\\match.MP4"), "mp4");
  assert.equal(extensionOf("/var/tmp/match.mov"), "mov");
  assert.equal(extensionOf("no-extension"), "");
});

test("an empty or oversized file is refused before anything is signed", () => {
  assert.match(validateFile(file({ size: 0 })), /empty/);
  assert.match(
    validateFile(file({ size: MAX_UPLOAD_BYTES + 1 })),
    /larger than/,
  );
  assert.equal(validateFile(file({ size: MAX_UPLOAD_BYTES })), null);
});

test("a resume needs the same name, size, and modified time", () => {
  const hint = {
    video_id: "v",
    game_id: "g",
    name: "match.mp4",
    size: PART + 1000,
    last_modified: 1_700_000_000_000,
  };
  assert.equal(sameFile(hint, file()), true);
  // A different file with the same name must not resume the old upload.
  assert.equal(sameFile(hint, file({ size: PART + 999 })), false);
  assert.equal(sameFile(hint, file({ lastModified: 1 })), false);
  assert.equal(sameFile(hint, file({ name: "other.mp4" })), false);
});

test("part ranges tile the file exactly once, with a short last part", () => {
  const total = PART * 2 + 17;
  assert.deepEqual(partRange(1, PART, total), { start: 0, end: PART });
  assert.deepEqual(partRange(2, PART, total), { start: PART, end: PART * 2 });
  assert.deepEqual(partRange(3, PART, total), {
    start: PART * 2,
    end: total,
  });
});

test("progress comes from the server's confirmed parts", () => {
  const total = PART * 2 + 17;
  assert.equal(storedFraction([], PART, total), 0);
  assert.equal(
    Math.round(storedFraction([1], PART, total) * 100),
    Math.round((PART / total) * 100),
  );
  assert.equal(storedFraction([1, 2, 3], PART, total), 1);
});

test("progress never exceeds one, even on a stale part list", () => {
  assert.equal(storedFraction([1, 2, 3, 4], PART, PART), 1);
  assert.equal(storedFraction([1], PART, 0), 0);
});

test("byte sizes read plainly", () => {
  assert.equal(formatBytes(512), "512 B");
  assert.equal(formatBytes(1024), "1.0 KB");
  assert.equal(formatBytes(32 * 1024 * 1024), "32 MB");
  assert.equal(formatBytes(8 * 1024 * 1024 * 1024), "8.0 GB");
});

test("at most three parts are ever in flight", async () => {
  let running = 0;
  let peak = 0;
  const done = [];
  await inParallel([1, 2, 3, 4, 5, 6, 7], 3, async (item) => {
    running += 1;
    peak = Math.max(peak, running);
    await new Promise((resolve) => setTimeout(resolve, 5));
    running -= 1;
    done.push(item);
  });
  assert.equal(peak, 3);
  assert.deepEqual(
    done.sort((a, b) => a - b),
    [1, 2, 3, 4, 5, 6, 7],
  );
});

test("a failing part stops the run and surfaces its error", async () => {
  await assert.rejects(
    inParallel([1, 2, 3], 3, async (item) => {
      if (item === 2) throw new Error("part 2 refused");
    }),
    /part 2 refused/,
  );
});

test("an empty work list starts no workers", async () => {
  let calls = 0;
  await inParallel([], 3, async () => {
    calls += 1;
  });
  assert.equal(calls, 0);
});
