import assert from "node:assert/strict";
import test from "node:test";
import { mondayOf, parsePlanForm, weekLabel } from "../apps/web/lib/plans.ts";

const slugs = new Set(["gate-scan", "two-look-receive"]);
const players = new Set(["11111111-1111-4111-8111-111111111111"]);
const form = {
  title: " Scanning week ",
  week: "2026-09-24",
  target: "team",
  drills: ["gate-scan", "", "two-look-receive"],
  notes: ["Twice", "ignored", ""],
};

test("mondayOf snaps any day to its UTC Monday", () => {
  assert.equal(mondayOf(new Date("2026-09-24T12:00:00Z")), "2026-09-21");
  assert.equal(mondayOf(new Date("2026-09-21T00:00:00Z")), "2026-09-21");
  assert.equal(mondayOf(new Date("2026-09-27T23:59:00Z")), "2026-09-21");
  assert.equal(weekLabel("2026-09-21"), "Week of Sep 21");
});

test("parsePlanForm keeps chosen drills and snaps the week", () => {
  const result = parsePlanForm(form, slugs, players);
  assert.deepEqual(result, {
    ok: true,
    plan: {
      title: "Scanning week",
      week_of: "2026-09-21",
      player_id: null,
      items: [
        { drill_slug: "gate-scan", note: "Twice" },
        { drill_slug: "two-look-receive", note: "" },
      ],
    },
  });
});

test("parsePlanForm refuses bad input", () => {
  for (const change of [
    { title: "" },
    { week: "" },
    { target: "22222222-2222-4222-8222-222222222222" },
    { drills: ["", ""] },
    { drills: ["made-up"] },
    { drills: Array(9).fill("gate-scan"), notes: [] },
    { notes: ["x".repeat(201)] },
  ]) {
    assert.equal(
      parsePlanForm({ ...form, ...change }, slugs, players).ok,
      false,
      JSON.stringify(change).slice(0, 60),
    );
  }
  const one = parsePlanForm(
    { ...form, target: [...players][0] },
    slugs,
    players,
  );
  assert.equal(one.ok && one.plan.player_id, [...players][0]);
});
