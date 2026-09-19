import assert from "node:assert/strict";
import test from "node:test";
import {
  isTextEntryTarget,
  reviewShortcut,
  validClipBounds,
} from "../apps/web/lib/marking.ts";
import {
  draftStorageKey,
  restoreDrafts,
  serializeDrafts,
} from "../apps/web/lib/review-drafts.ts";

test("I and O mark clip bounds regardless of letter case", () => {
  assert.deepEqual(reviewShortcut("i", false, false), { type: "mark-in" });
  assert.deepEqual(reviewShortcut("I", false, false), { type: "mark-in" });
  assert.deepEqual(reviewShortcut("o", false, false), { type: "mark-out" });
  assert.deepEqual(reviewShortcut("O", false, false), { type: "mark-out" });
});

test("arrow shortcuts preserve their one and ten second steps", () => {
  assert.deepEqual(reviewShortcut("ArrowLeft", false, false), {
    type: "seek",
    seconds: -1,
  });
  assert.deepEqual(reviewShortcut("ArrowRight", true, false), {
    type: "seek",
    seconds: 10,
  });
});

test("review shortcuts are suppressed while editing text", () => {
  for (const key of [" ", "i", "o", "j", "k", "l", "ArrowLeft"]) {
    assert.equal(reviewShortcut(key, false, true), null, key);
  }
  assert.deepEqual(reviewShortcut("Escape", false, true), {
    type: "focus-video",
  });
  assert.deepEqual(reviewShortcut("Enter", false, true), {
    type: "save-draft",
  });
});

test("judgment shortcuts select verdict, comment, and save", () => {
  assert.deepEqual(reviewShortcut("1", false, false), {
    type: "select-verdict",
    verdict: "applied",
  });
  assert.deepEqual(reviewShortcut("2", false, false), {
    type: "select-verdict",
    verdict: "opportunity",
  });
  assert.deepEqual(reviewShortcut("3", false, false), {
    type: "select-verdict",
    verdict: "not_relevant",
  });
  assert.deepEqual(reviewShortcut("c", false, false), {
    type: "focus-comment",
  });
  assert.deepEqual(reviewShortcut("Enter", false, false), {
    type: "save-draft",
  });
});

test("input, textarea, select, and contenteditable targets count as text entry", () => {
  for (const tagName of ["INPUT", "TEXTAREA", "SELECT"]) {
    assert.equal(
      isTextEntryTarget({ tagName, isContentEditable: false }),
      true,
      tagName,
    );
  }
  assert.equal(
    isTextEntryTarget({ tagName: "DIV", isContentEditable: true }),
    true,
  );
  assert.equal(
    isTextEntryTarget({ tagName: "BUTTON", isContentEditable: false }),
    false,
  );
  assert.equal(isTextEntryTarget(null), false);
});

test("clip bounds must be ordered, non-negative, and within the video", () => {
  assert.equal(validClipBounds(1_000, 4_000, 10_000), true);
  assert.equal(validClipBounds(-1, 4_000, 10_000), false);
  assert.equal(validClipBounds(4_000, 4_000, 10_000), false);
  assert.equal(validClipBounds(5_000, 4_000, 10_000), false);
  assert.equal(validClipBounds(1_000, 10_001, 10_000), false);
});

test("five complete review drafts survive an exact storage round trip", () => {
  const scope = {
    coachId: "00000000-0000-4000-8000-00000000000c",
    videoId: "10000000-0000-4000-8000-000000000001",
    playerId: "20000000-0000-4000-8000-000000000002",
    goalId: "30000000-0000-4000-8000-000000000003",
  };
  const drafts = Array.from({ length: 5 }, (_, index) => ({
    localId: `60000000-0000-4000-8000-00000000000${index}`,
    observationId: `40000000-0000-4000-8000-00000000000${index}`,
    judgmentId: `50000000-0000-4000-8000-00000000000${index}`,
    position: index,
    clipStartMs: index * 2_000,
    clipEndMs: index * 2_000 + 1_500,
    verdict:
      index === 4 ? "not_relevant" : index % 2 ? "opportunity" : "applied",
    commentText: `Coach comment ${index}`,
    version: index + 1,
    synced: {
      clipStartMs: index * 2_000,
      clipEndMs: index * 2_000 + 1_500,
      verdict:
        index === 4 ? "not_relevant" : index % 2 ? "opportunity" : "applied",
      commentText: `Coach comment ${index}`,
      version: index + 1,
    },
    saveState: "saved",
    conflict: null,
  }));

  const stored = serializeDrafts(scope, drafts);
  assert.deepEqual(restoreDrafts(stored, scope), drafts);
  assert.equal(
    draftStorageKey(scope),
    "shoulder:review-drafts:v2:00000000-0000-4000-8000-00000000000c:10000000-0000-4000-8000-000000000001:20000000-0000-4000-8000-000000000002:30000000-0000-4000-8000-000000000003",
  );
});

test("a draft key belongs to one coach, video, player and goal", () => {
  const base = {
    coachId: "coach-a",
    videoId: "video-a",
    playerId: "player-a",
    goalId: "goal-a",
  };
  const key = draftStorageKey(base);
  // Two coaches sharing a browser profile must not share a key. Keyed on
  // video and player alone, the second coach restored the first one's unsent
  // text and could submit it under their own name.
  assert.notEqual(draftStorageKey({ ...base, coachId: "coach-b" }), key);
  // And the goal, because restore validates it: a key that omitted it read
  // the other goal's drafts, rejected them, then overwrote them.
  assert.notEqual(draftStorageKey({ ...base, goalId: "goal-b" }), key);
  assert.notEqual(draftStorageKey({ ...base, videoId: "video-b" }), key);
  assert.notEqual(draftStorageKey({ ...base, playerId: "player-b" }), key);
  // A player with no active goal still gets a key of its own.
  assert.equal(
    draftStorageKey({ ...base, goalId: null }),
    "shoulder:review-drafts:v2:coach-a:video-a:player-a:no-goal",
  );
});

test("draft restore fails closed for corrupt or mismatched local data", () => {
  const scope = {
    coachId: "coach-a",
    videoId: "video-a",
    playerId: "player-a",
    goalId: "goal-a",
  };
  assert.deepEqual(restoreDrafts("not json", scope), []);
  assert.deepEqual(
    restoreDrafts(
      JSON.stringify({
        schema: 1,
        scope: { ...scope, playerId: "player-b" },
        drafts: [],
      }),
      scope,
    ),
    [],
  );
});
