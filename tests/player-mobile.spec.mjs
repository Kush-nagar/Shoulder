import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const origin = "http://127.0.0.1:3000";
const api = "http://127.0.0.1:8000";
const mail = "http://127.0.0.1:54324";
const python =
  process.platform === "win32"
    ? ".venv/Scripts/python.exe"
    : ".venv/bin/python";
const viewports = [
  [320, 568],
  [360, 800],
  [375, 812],
  [390, 844],
  [430, 932],
  [768, 1024],
];
const createdEmails = new Set();

function psql(sql, user = "postgres") {
  const password =
    user === "postgres"
      ? undefined
      : new URL(
          (process.env.DATABASE_URL ?? "").replace(
            "postgresql+psycopg:",
            "postgresql:",
          ),
        ).password;
  const connection =
    user === "postgres" ? [] : ["-h", "127.0.0.1", "-p", "5432"];
  return execFileSync(
    "docker",
    [
      "exec",
      "-i",
      "supabase_db_shoulder-local",
      "psql",
      "-U",
      user,
      ...connection,
      "-d",
      "postgres",
      "-q",
      "-v",
      "ON_ERROR_STOP=1",
      "-Atc",
      sql,
    ],
    {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
      env: { ...process.env, ...(password ? { PGPASSWORD: password } : {}) },
    },
  ).trim();
}

function quoted(value) {
  return `'${String(value).replaceAll("'", "''")}'`;
}

function resetLocalWorkspace() {
  psql(
    "TRUNCATE app.review_publication_item, app.evidence_clip, app.review_publication, app.judgment_revision, app.judgment, app.observation, app.processing_job, app.video_upload_part, app.video, app.game, app.development_goal, app.player, app.team_membership, app.team",
  );
}

function emptyLocalBucket() {
  execFileSync(
    "docker",
    [
      "compose",
      "--env-file",
      ".env.local",
      "-f",
      "infra/compose.yaml",
      "run",
      "--rm",
      "mc",
      "-ec",
      'mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null; mc rm --recursive --force --dangerous local/shoulder-local >/dev/null 2>&1 || true',
    ],
    { stdio: ["ignore", "ignore", "pipe"] },
  );
}

async function deleteCreatedUsers(request) {
  if (createdEmails.size === 0) return;
  const status = JSON.parse(
    execFileSync(".tools/supabase/supabase.exe", ["status", "-o", "json"], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }),
  );
  if (status.API_URL !== "http://127.0.0.1:54321")
    throw new Error("Local cleanup only");
  const headers = {
    apikey: status.SERVICE_ROLE_KEY,
    Authorization: `Bearer ${status.SERVICE_ROLE_KEY}`,
  };
  for (const email of createdEmails) {
    const users = await fetch(
      `${status.API_URL}/auth/v1/admin/users?filter=${encodeURIComponent(email)}`,
      { headers },
    );
    if (!users.ok) throw new Error("Local fixture lookup failed");
    for (const user of (await users.json()).users.filter(
      (candidate) => candidate.email === email,
    )) {
      const deleted = await fetch(
        `${status.API_URL}/auth/v1/admin/users/${user.id}`,
        { method: "DELETE", headers },
      );
      if (!deleted.ok) throw new Error("Local fixture deletion failed");
    }
  }
  const listing = await (await request.get(`${mail}/api/v1/messages`)).json();
  const ids = listing.messages
    .filter((message) => message.To.some((to) => createdEmails.has(to.Address)))
    .map((message) => message.ID);
  if (ids.length) {
    await request.delete(`${mail}/api/v1/messages`, { data: { IDs: ids } });
  }
  createdEmails.clear();
}

test.beforeEach(resetLocalWorkspace);
test.afterEach(async ({ request }) => {
  resetLocalWorkspace();
  emptyLocalBucket();
  await deleteCreatedUsers(request);
});

async function signIn(context, request, label) {
  const page = await context.newPage();
  const email = `player-mobile-${label}-${randomUUID()}@example.test`;
  createdEmails.add(email);
  await page.goto("/auth/sign-in");
  await page.getByLabel("Email address").fill(email);
  await page.getByRole("button", { name: "Email a sign-in link" }).click();
  await expect(page.getByRole("status")).toContainText("check your email");
  let messageId;
  await expect
    .poll(async () => {
      const listing = await (
        await request.get(`${mail}/api/v1/messages`)
      ).json();
      messageId = listing.messages.find((message) =>
        message.To.some((to) => to.Address === email),
      )?.ID;
      return Boolean(messageId);
    })
    .toBe(true);
  const message = await (
    await request.get(`${mail}/api/v1/message/${messageId}`)
  ).json();
  const link = message.HTML.match(
    /href="([^"]*\/auth\/v1\/verify[^"]*)"/,
  )[1].replaceAll("&amp;", "&");
  const verification = await request.get(link, { maxRedirects: 0 });
  const exchanged = await context.request.get(verification.headers().location, {
    maxRedirects: 0,
  });
  expect(exchanged.headers().location).toBe(`${origin}/auth/session`);
  const identity = await context.request.get("/api/auth/identity");
  expect(identity.status()).toBe(200);
  const { user_id: userId } = await identity.json();
  await page.close();
  return { email, userId };
}

async function bootstrapTeam(coachId, request) {
  const response = await request.post(`${api}/v1/teams`, {
    headers: {
      "X-Operator-Token": process.env.OPERATOR_BOOTSTRAP_TOKEN ?? "",
    },
    data: {
      name: "Shoulder Mobile FC",
      age_group: "U16",
      coach_user_id: coachId,
      season_label: "Season 2026",
      season_end_at: new Date(Date.now() + 86_400_000).toISOString(),
    },
  });
  expect(response.status()).toBe(201);
  return (await response.json()).team_id;
}

function insertPlayer(teamId, userId, displayName) {
  const playerId = psql(`
    INSERT INTO app.player (team_id, display_name, user_id)
    VALUES (${quoted(teamId)}, ${quoted(displayName)}, ${quoted(userId)})
    RETURNING id
  `);
  psql(`
    INSERT INTO app.team_membership (team_id, user_id, role)
    VALUES (${quoted(teamId)}, ${quoted(userId)}, 'player')
  `);
  return playerId;
}

function seedDomain(teamId, coachId, playerId) {
  const goalId = psql(`
    INSERT INTO app.development_goal (player_id, title, description, created_by)
    VALUES (
      ${quoted(playerId)}, 'Scan before receiving',
      'Look over both shoulders before the ball arrives.', ${quoted(coachId)}
    ) RETURNING id
  `);
  const gameId = psql(`
    INSERT INTO app.game (team_id, played_at, opponent, created_by)
    VALUES (${quoted(teamId)}, '2026-09-12T15:00:00Z', 'River City', ${quoted(coachId)})
    RETURNING id
  `);
  const videoId = randomUUID();
  const fixture = JSON.parse(
    execFileSync(
      python,
      [
        "-m",
        "scripts.seed_player_fixture",
        "--video-id",
        videoId,
        "--seconds",
        "10",
        "--skip-thumbnails",
      ],
      { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
    ),
  );
  psql(`
    INSERT INTO app.video (
      id, game_id, original_key, original_filename, content_type, size_bytes,
      uploaded_by, status, playback_key, duration_ms, width, height, fps,
      ready_at, derivatives_expires_at
    ) VALUES (
      ${quoted(videoId)}, ${quoted(gameId)},
      ${quoted(`originals/${videoId}/source.mp4`)}, 'match.mp4', 'video/mp4',
      ${fixture.size_bytes}, ${quoted(coachId)}, 'ready',
      ${quoted(`playback/${videoId}/coach-720p.mp4`)}, ${fixture.duration_ms},
      ${fixture.width}, ${fixture.height}, ${fixture.fps}, now(),
      now() + interval '30 days'
    )
  `);
  return { goalId, gameId, videoId };
}

async function createJudgments(coachContext, videoId, playerId, goalId) {
  const bounds = [
    [1000, 2200],
    [3000, 4200],
    [5000, 6200],
  ];
  const judgments = [];
  for (const [index, [start, end]] of bounds.entries()) {
    const observation = await coachContext.request.post(
      `/api/videos/${videoId}/observations`,
      {
        headers: { Origin: origin },
        data: {
          client_id: randomUUID(),
          player_id: playerId,
          t_start_ms: start,
          t_end_ms: end,
        },
      },
    );
    expect(observation.status()).toBe(201);
    const judgment = await coachContext.request.post(
      `/api/observations/${(await observation.json()).id}/judgment`,
      {
        headers: { Origin: origin },
        data: {
          goal_id: goalId,
          verdict: index === 1 ? "opportunity" : "applied",
          comment_text: `Coach sentence ${index + 1}.`,
          clip_start_ms: start,
          clip_end_ms: end,
        },
      },
    );
    expect(judgment.status()).toBe(201);
    judgments.push(await judgment.json());
  }
  return judgments;
}

function publish({ coachId, gameId, playerId, goalId, judgments, replaces }) {
  const judgmentIds = judgments.map((item) => quoted(item.id)).join(",");
  const versions = judgments.map((item) => item.version).join(",");
  return psql(
    `
    BEGIN;
    SET LOCAL app.user_id = ${quoted(coachId)};
    SELECT id FROM private.request_review_publication(
      ${quoted(gameId)}, ${quoted(playerId)}, ${quoted(goalId)},
      ${replaces ? quoted(replaces) : "NULL"}, ${quoted(`browser-${randomUUID()}`)},
      ARRAY[${judgmentIds}]::uuid[], ARRAY[${versions}]::bigint[]
    );
    COMMIT;
  `,
    "shoulder_api",
  );
}

function runClipExports() {
  execFileSync(
    python,
    [
      "-c",
      "from services.worker.main import Worker\nworker = Worker('player-mobile-fixture')\nwhile worker.run_once(): pass",
    ],
    { stdio: ["ignore", "ignore", "pipe"] },
  );
}

test("linked player sees only current clips across phone viewports", async ({
  browser,
  request,
}, testInfo) => {
  test.setTimeout(240_000);
  const coachContext = await browser.newContext({ baseURL: origin });
  const playerContext = await browser.newContext({ baseURL: origin });
  const otherContext = await browser.newContext({ baseURL: origin });
  try {
    const coach = await signIn(coachContext, request, "coach");
    const teamId = await bootstrapTeam(coach.userId, request);
    const player = await signIn(playerContext, request, "player-a");
    const other = await signIn(otherContext, request, "player-b");
    const playerId = insertPlayer(teamId, player.userId, "Alex Morgan");
    insertPlayer(teamId, other.userId, "Bailey Chen");
    const { goalId, gameId, videoId } = seedDomain(
      teamId,
      coach.userId,
      playerId,
    );
    let judgments = await createJudgments(
      coachContext,
      videoId,
      playerId,
      goalId,
    );
    const firstPublication = publish({
      coachId: coach.userId,
      gameId,
      playerId,
      goalId,
      judgments,
    });
    runClipExports();
    expect(
      psql(
        `SELECT status FROM app.review_publication WHERE id = ${quoted(firstPublication)}`,
      ),
    ).toBe("published");

    const page = await playerContext.newPage();
    page.setDefaultTimeout(10_000);
    await page.addInitScript(() => {
      window.__shoulderVitals = { cls: 0, lcp: 0 };
      try {
        new PerformanceObserver((list) => {
          const entries = list.getEntries();
          window.__shoulderVitals.lcp = entries.at(-1)?.startTime ?? 0;
        }).observe({ type: "largest-contentful-paint", buffered: true });
        new PerformanceObserver((list) => {
          for (const entry of list.getEntries()) {
            if (!entry.hadRecentInput) {
              window.__shoulderVitals.cls += entry.value;
            }
          }
        }).observe({ type: "layout-shift", buffered: true });
      } catch {
        // Firefox/WebKit do not expose every Web Vitals entry type.
      }
    });
    for (const [width, height] of viewports) {
      await page.setViewportSize({ width, height });
      await page.goto("/");
      await expect(page).toHaveURL(`${origin}/player`);
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(
        "Your clips.",
      );
      await expect(page.getByText("Scan before receiving")).toBeVisible();
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth),
      ).toBeLessThanOrEqual(width + 1);
      const results = await new AxeBuilder({ page }).analyze();
      expect(results.violations).toEqual([]);
      const screenshotPath = testInfo.outputPath(
        `player-home-${width}x${height}.png`,
      );
      await page.screenshot({
        path: screenshotPath,
        fullPage: true,
      });
      await testInfo.attach(`player-home-${width}x${height}`, {
        path: screenshotPath,
        contentType: "image/png",
      });
    }
    if (testInfo.project.name === "chromium") {
      await page.waitForTimeout(100);
      const vitals = await page.evaluate(() => {
        const navigation = performance.getEntriesByType("navigation")[0];
        const firstContentfulPaint = performance
          .getEntriesByName("first-contentful-paint")
          .at(-1)?.startTime;
        return {
          ...window.__shoulderVitals,
          domContentLoaded:
            navigation?.domContentLoadedEventEnd - navigation?.startTime,
          firstContentfulPaint,
        };
      });
      expect(vitals.lcp).toBeGreaterThan(0);
      expect(vitals.cls).toBeLessThanOrEqual(0.1);
      await testInfo.attach("player-home-web-vitals", {
        body: JSON.stringify(vitals, null, 2),
        contentType: "application/json",
      });
    }

    const homeHtml = await page.content();
    expect(homeHtml).not.toContain(videoId);
    expect(homeHtml).not.toContain("playback/");
    const accountMenu = page.locator('summary[aria-label="Account menu"]');
    await accountMenu.focus();
    await expect(accountMenu).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
    await page.keyboard.press("Enter");
    await expect(accountMenu.locator("..")).not.toHaveAttribute("open", "");

    await page.setViewportSize({ width: 375, height: 812 });
    await page.locator(`a[href="/player/goals/${goalId}"]`).click();
    await expect(page.getByText("You did this.")).toBeVisible();
    await expect(page.getByText("Coach sentence 1.")).toBeVisible();
    await expect(page.getByText("not_relevant")).toHaveCount(0);
    const currentVideo = page.locator("video:not([aria-hidden='true'])");
    await expect(currentVideo).toHaveAttribute("src", /\/clips\//);
    await expect(currentVideo).toHaveAttribute("preload", "metadata");
    await expect(page.locator("video[aria-hidden='true']")).toHaveCount(1);
    await expect(page.locator("video")).toHaveCount(2);
    const goalHtml = await page.content();
    expect(goalHtml).not.toContain(videoId);
    expect(goalHtml).not.toContain("playback/");

    const ownEvidence = await playerContext.request.get(
      `/api/player/goals/${goalId}/evidence`,
    );
    expect(ownEvidence.status()).toBe(200);
    expect(ownEvidence.headers()["cache-control"]).toContain("private");
    expect(ownEvidence.headers()["cache-control"]).toContain("no-store");
    const ownBody = await ownEvidence.text();
    expect(ownBody).not.toContain(videoId);
    expect(ownBody).not.toContain("storage_key");
    expect(ownBody).not.toContain("playback/");
    const firstItem = JSON.parse(ownBody)[0].items[0];

    const ownSign = await playerContext.request.post(
      `/api/player/judgments/${firstItem.judgment_id}/clip-url`,
      {
        headers: { Origin: origin },
        data: {
          expected_published_revision_id: firstItem.published_revision_id,
        },
      },
    );
    expect(ownSign.status()).toBe(200);
    expect(ownSign.headers()["cache-control"]).toContain("private");
    expect(ownSign.headers()["cache-control"]).toContain("no-store");
    expect(await ownSign.text()).not.toContain(videoId);

    const deniedRead = await otherContext.request.get(
      `/api/player/goals/${goalId}/evidence`,
    );
    expect(deniedRead.status()).toBe(200);
    expect(await deniedRead.json()).toEqual([]);
    const deniedSign = await otherContext.request.post(
      `/api/player/judgments/${firstItem.judgment_id}/clip-url`,
      {
        headers: { Origin: origin },
        data: {
          expected_published_revision_id: firstItem.published_revision_id,
        },
      },
    );
    expect(deniedSign.status()).toBe(409);

    const edited = await coachContext.request.patch(
      `/api/judgments/${judgments[1].id}`,
      {
        headers: { Origin: origin, "If-Match": '"1"' },
        data: {
          verdict: "opportunity",
          comment_text: "Notice the space before your first touch.",
          clip_start_ms: 3000,
          clip_end_ms: 4200,
        },
      },
    );
    expect(edited.status()).toBe(200);
    judgments = [judgments[0], await edited.json(), judgments[2]];
    const replacement = publish({
      coachId: coach.userId,
      gameId,
      playerId,
      goalId,
      judgments,
      replaces: firstPublication,
    });
    runClipExports();
    expect(
      psql(
        `SELECT status FROM app.review_publication WHERE id = ${quoted(replacement)}`,
      ),
    ).toBe("published");

    await page.evaluate(() => {
      window.__shoulderPairs = [];
      const record = () => {
        window.__shoulderPairs.push({
          text: document.querySelector("#clip-title")?.textContent ?? "",
          src:
            document
              .querySelector("video:not([aria-hidden='true'])")
              ?.getAttribute("src") ?? "",
        });
      };
      record();
      window.__shoulderObserver = new MutationObserver(record);
      window.__shoulderObserver.observe(document.body, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ["src"],
      });
    });
    const next = page.getByRole("button", { name: "Next" });
    await next.focus();
    await expect(next).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(
      page.getByText("Notice the space before your first touch."),
    ).toBeVisible();
    await expect(currentVideo).toHaveAttribute(
      "src",
      new RegExp(`/clips/${judgments[1].id}/2\\.mp4`),
    );
    const pairs = await page.evaluate(() => {
      window.__shoulderObserver.disconnect();
      return window.__shoulderPairs;
    });
    expect(
      pairs.some(
        ({ text, src }) =>
          text.includes("Coach sentence 2.") && src.includes("/2.mp4"),
      ),
    ).toBe(false);
    expect(
      pairs.some(
        ({ text, src }) =>
          text.includes("Notice the space") && src.includes("/1.mp4"),
      ),
    ).toBe(false);
    await expect(page.locator("video")).toHaveCount(2);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBe(375);
    const finalA11y = await new AxeBuilder({ page }).analyze();
    expect(finalA11y.violations).toEqual([]);
    const evidenceScreenshot = testInfo.outputPath(
      "player-evidence-375x812.png",
    );
    await page.screenshot({
      path: evidenceScreenshot,
      fullPage: true,
    });
    await testInfo.attach("player-evidence-375x812", {
      path: evidenceScreenshot,
      contentType: "image/png",
    });
  } finally {
    await Promise.all([
      coachContext.close(),
      playerContext.close(),
      otherContext.close(),
    ]);
  }
});
