import assert from "node:assert/strict";
import test from "node:test";
import {
  isTextEntryTarget,
  reviewShortcut,
  validClipBounds,
} from "../apps/web/lib/marking.ts";

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
