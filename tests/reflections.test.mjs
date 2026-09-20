import assert from "node:assert/strict";
import test from "node:test";
import {
  clearAllReflectionDrafts,
  clearReflectionDraft,
  reflectionDraftKey,
  restoreReflectionDraft,
  serializeReflectionDraft,
} from "../apps/web/lib/reflection-drafts.ts";

class MemoryStorage {
  values = new Map();

  get length() {
    return this.values.size;
  }

  key(index) {
    return [...this.values.keys()][index] ?? null;
  }

  getItem(key) {
    return this.values.get(key) ?? null;
  }

  setItem(key, value) {
    this.values.set(key, value);
  }

  removeItem(key) {
    this.values.delete(key);
  }
}

const player = "11111111-1111-4111-8111-111111111111";
const judgment = "22222222-2222-4222-8222-222222222222";

test("reflection draft keeps unsent text and retry identity", () => {
  const draft = {
    text: "I noticed the space behind me.",
    pending: {
      idempotencyKey: "save-1",
      requestCreatedAt: "2026-09-20T10:00:00.000Z",
      intent: "create",
      expectedReflectionId: null,
      expectedEtag: null,
      text: "I noticed the space behind me.",
    },
  };
  assert.deepEqual(
    restoreReflectionDraft(serializeReflectionDraft(draft)),
    draft,
  );
});

test("invalid cached reflection data fails closed", () => {
  assert.equal(restoreReflectionDraft("not-json"), null);
  assert.equal(restoreReflectionDraft('{"text":4}'), null);
  assert.equal(
    restoreReflectionDraft('{"text":"ok","pending":{"text":"secret"}}'),
    null,
  );
});

test("delete clears only the named reflection cache", () => {
  const storage = new MemoryStorage();
  const key = reflectionDraftKey(player, judgment);
  storage.setItem(key, "reflection text");
  storage.setItem(reflectionDraftKey(player, crypto.randomUUID()), "other");
  storage.setItem("shoulder:unrelated", "keep");
  clearReflectionDraft(storage, player, judgment);
  assert.equal(storage.getItem(key), null);
  assert.equal(storage.length, 2);
});

test("sign-out clears every queued reflection text and leaves other cache", () => {
  const storage = new MemoryStorage();
  storage.setItem(reflectionDraftKey(player, judgment), "first secret");
  storage.setItem(
    reflectionDraftKey(crypto.randomUUID(), crypto.randomUUID()),
    "second secret",
  );
  storage.setItem("shoulder:upload:resume", "keep");
  clearAllReflectionDrafts(storage);
  assert.equal(storage.length, 1);
  assert.equal(storage.getItem("shoulder:upload:resume"), "keep");
});
