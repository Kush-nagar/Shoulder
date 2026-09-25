import assert from "node:assert/strict";
import test from "node:test";
import { firstName } from "../apps/web/app/player/identity.ts";
import {
  drillOfTheDay,
  drills,
  drillsForGoal,
  focuses,
  focusFromSlug,
  focusSlug,
} from "../apps/web/content/drills.ts";

test("drill library is the 12-drill seed with unique slugs and known focuses", () => {
  assert.equal(drills.length, 12);
  assert.equal(new Set(drills.map((drill) => drill.slug)).size, 12);
  for (const drill of drills) {
    assert.ok(focuses.includes(drill.focus));
    assert.equal(drill.steps.length, 5);
    assert.doesNotMatch(JSON.stringify(drill), /—|–/);
  }
  for (const focus of focuses)
    assert.equal(focusFromSlug(focusSlug(focus)), focus);
});

test("goal matching and the daily pick stay inside the goal's drills", () => {
  const goal = { title: "Check your shoulder before you receive" };
  const matched = drillsForGoal(goal).map((drill) => drill.slug);
  assert.ok(matched.includes("two-look-receive"));
  assert.ok(!matched.includes("jockey-show-wide"));
  for (let day = 0; day < 30; day++) {
    const pick = drillOfTheDay(goal, new Date(Date.UTC(2026, 8, 1 + day)));
    assert.ok(matched.includes(pick.slug));
  }
  assert.ok(drillOfTheDay(null));
  assert.deepEqual(drillsForGoal(null), []);
});

test("greeting uses a first name only when it plainly is one", () => {
  assert.equal(firstName("Sam Okafor"), "Sam");
  assert.equal(firstName("visitor-a-1727@example.com"), null);
  assert.equal(firstName("player42"), null);
  assert.equal(firstName(""), null);
});
