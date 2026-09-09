import assert from "node:assert/strict";
import test from "node:test";
import { parseRoster } from "../apps/web/lib/roster.ts";

const names = (rows) => rows.map((row) => row.display_name);
const errors = (rows) => rows.map((row) => row.errors);

test("parses name, number, position and treats blank lines as spacing", () => {
  const rows = parseRoster(
    "Ada Nkemdirim, 7, Winger\n\n  \nBo Sun, 9, Striker\n",
  );
  assert.equal(rows.length, 2);
  assert.deepEqual(names(rows), ["Ada Nkemdirim", "Bo Sun"]);
  assert.deepEqual(rows[0], {
    display_name: "Ada Nkemdirim",
    jersey_number: 7,
    position: "Winger",
    errors: [],
  });
  assert.deepEqual(errors(rows), [[], []]);
});

test("a trailing comma means no position, not a fourth field", () => {
  const rows = parseRoster("Ada, 7,\nBo, 9, ,\n");
  assert.deepEqual(
    rows.map((row) => row.position),
    [null, null],
  );
  assert.deepEqual(errors(rows), [[], []]);
});

test("missing optional fields become null without an error", () => {
  const rows = parseRoster("Ada\nBo,\nCam, , Striker");
  assert.deepEqual(
    rows.map((row) => [row.jersey_number, row.position]),
    [
      [null, null],
      [null, null],
      [null, "Striker"],
    ],
  );
  assert.deepEqual(errors(rows), [[], [], []]);
});

test("a duplicate jersey inside the paste flags every offending row", () => {
  const rows = parseRoster("Ada, 7\nBo, 9\nCam, 7");
  assert.deepEqual(errors(rows), [
    ["Number is used more than once in this paste."],
    [],
    ["Number is used more than once in this paste."],
  ]);
  // A repeated blank number is not a duplicate.
  assert.deepEqual(errors(parseRoster("Ada\nBo")), [[], []]);
});

test("a number outside 0 to 99 is rejected and 0 to 99 is accepted", () => {
  for (const bad of ["100", "-1", "1.5", "7a", " 07 8", "٧"]) {
    const [row] = parseRoster(`Ada, ${bad}`);
    assert.deepEqual(row.errors, [
      "Number must be a whole number from 0 to 99.",
    ]);
    assert.equal(row.jersey_number, null);
  }
  for (const [text, value] of [
    ["0", 0],
    ["07", 7],
    ["99", 99],
  ]) {
    const [row] = parseRoster(`Ada, ${text}`);
    assert.deepEqual(row.errors, []);
    assert.equal(row.jersey_number, value);
  }
});

test("a name outside 1 to 80 characters is rejected", () => {
  assert.deepEqual(parseRoster(`${"x".repeat(80)}, 7`)[0].errors, []);
  assert.deepEqual(parseRoster(`${"x".repeat(81)}, 7`)[0].errors, [
    "Name must be 1 to 80 characters.",
  ]);
  assert.deepEqual(parseRoster(", 7, Winger")[0].errors, [
    "Name must be 1 to 80 characters.",
  ]);
});

test("a long position and a fourth field are reported per row", () => {
  assert.deepEqual(parseRoster(`Ada, 7, ${"x".repeat(41)}`)[0].errors, [
    "Position must be 40 characters or fewer.",
  ]);
  assert.deepEqual(parseRoster("Ada, 7, Winger, extra")[0].errors, [
    "Use name, number, position.",
  ]);
});

test("empty input produces no rows", () => {
  assert.deepEqual(parseRoster(""), []);
  assert.deepEqual(parseRoster("\n\n   \n"), []);
});
