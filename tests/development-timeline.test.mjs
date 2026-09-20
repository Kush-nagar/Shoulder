import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  evidenceDotLabel,
  verdictText,
} from "../apps/web/lib/development-timeline.ts";

test("five games form a discrete evidence record with text equivalents", () => {
  const games = Array.from({ length: 5 }, (_, gameIndex) => ({
    label: `vs Team ${gameIndex + 1}`,
    dots: Array.from({ length: 3 }, (_, clipIndex) => ({
      verdict: clipIndex % 2 === 0 ? "applied" : "opportunity",
      label: evidenceDotLabel(
        clipIndex % 2 === 0 ? "applied" : "opportunity",
        `vs Team ${gameIndex + 1}`,
        clipIndex + 1,
        3,
      ),
    })),
  }));

  assert.equal(games.length, 5);
  assert.equal(new Set(games.map((game) => game.label)).size, 5);
  assert.equal(games.flatMap((game) => game.dots).length, 15);
  assert.deepEqual(
    new Set(games.flatMap((game) => game.dots.map((dot) => dot.label))).size,
    15,
  );
  assert.equal(verdictText("applied"), "You did this.");
  assert.equal(verdictText("opportunity"), "Chance to do this.");
});

test("timeline UI exposes a text legend and names every dot link", () => {
  const source = readFileSync(
    "apps/web/components/development-timeline.tsx",
    "utf8",
  );
  assert.match(source, /aria-label="Evidence legend"/);
  assert.match(source, /aria-label=\{evidenceDotLabel\(/);
  assert.match(source, /<Dot filled \/> You did this\./);
  assert.match(source, /<Dot filled=\{false\} \/> Chance to do this\./);
});

test("timeline API and UI add no metric or comparison fields", () => {
  const contract = JSON.parse(
    readFileSync("packages/contracts/openapi.json", "utf8"),
  );
  const schemas = contract.components.schemas;
  for (const name of ["CoachEvidenceSet", "EvidenceDot", "EvidenceSet"]) {
    const keys = Object.keys(schemas[name].properties);
    assert.deepEqual(
      keys.filter((key) =>
        /score|percent|aggregate|average|rank|trend|comparison|total/i.test(
          key,
        ),
      ),
      [],
      name,
    );
  }

  const source = readFileSync(
    "apps/web/components/development-timeline.tsx",
    "utf8",
  );
  assert.doesNotMatch(
    source,
    /\b(score|percentage|average|ranking|trend|improvement)\b/i,
  );
});
