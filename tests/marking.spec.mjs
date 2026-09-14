import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";

const origin = "http://127.0.0.1:3000";
const api = "http://127.0.0.1:8000";
const mail = "http://127.0.0.1:54324";
const python =
  process.platform === "win32"
    ? ".venv/Scripts/python.exe"
    : ".venv/bin/python";

let createdEmail;

function psql(sql) {
  return execFileSync(
    "docker",
    [
      "exec",
      "-i",
      "supabase_db_shoulder-local",
      "psql",
      "-U",
      "postgres",
      "-d",
      "postgres",
      "-q",
      "-v",
      "ON_ERROR_STOP=1",
      "-Atc",
      sql,
    ],
    { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
  ).trim();
}

function quoted(value) {
  return `'${String(value).replace(/'/g, "''")}'`;
}

function resetLocalWorkspace() {
  psql(
    "TRUNCATE app.observation, app.processing_job, app.video_upload_part, app.video, app.game, app.development_goal, app.player, app.team_membership, app.team",
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

test.beforeEach(() => resetLocalWorkspace());

test.afterEach(async ({ request }) => {
  resetLocalWorkspace();
  emptyLocalBucket();
  if (!createdEmail) return;
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
  const users = await fetch(
    `${status.API_URL}/auth/v1/admin/users?filter=${encodeURIComponent(createdEmail)}`,
    { headers },
  );
  if (!users.ok) throw new Error("Local fixture lookup failed");
  for (const user of (await users.json()).users.filter(
    (candidate) => candidate.email === createdEmail,
  )) {
    const removed = await fetch(
      `${status.API_URL}/auth/v1/admin/users/${user.id}`,
      { method: "DELETE", headers },
    );
    if (!removed.ok) throw new Error("Local fixture deletion failed");
  }
  const messages = await (await request.get(`${mail}/api/v1/messages`)).json();
  const ids = messages.messages
    .filter((message) => message.To.some((to) => to.Address === createdEmail))
    .map((message) => message.ID);
  if (ids.length)
    await request.delete(`${mail}/api/v1/messages`, { data: { IDs: ids } });
  createdEmail = undefined;
});

async function signIn(page, context, request) {
  const email = `task14-${randomUUID()}@example.test`;
  createdEmail = email;
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
}

async function bootstrapTeam(context, request) {
  const identity = await context.request.get("/api/auth/identity");
  expect(identity.status()).toBe(200);
  const { user_id: coachId } = await identity.json();
  const created = await request.post(`${api}/v1/teams`, {
    headers: {
      "X-Operator-Token": process.env.OPERATOR_BOOTSTRAP_TOKEN ?? "",
    },
    data: {
      name: `Task 14 ${randomUUID().slice(0, 8)}`,
      age_group: "U14",
      coach_user_id: coachId,
      season_label: "Season 2026",
      season_end_at: new Date(Date.now() + 86_400_000).toISOString(),
    },
  });
  expect(created.status()).toBe(201);
  return { coachId, teamId: (await created.json()).team_id };
}

function seedFixture(videoId) {
  return JSON.parse(
    execFileSync(
      python,
      [
        "-m",
        "scripts.seed_player_fixture",
        "--video-id",
        videoId,
        "--seconds",
        "12",
      ],
      { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
    ),
  );
}

async function readyReview(page, context, request) {
  await signIn(page, context, request);
  const { coachId, teamId } = await bootstrapTeam(context, request);
  const playerId = psql(`
    INSERT INTO app.player (team_id, display_name, jersey_number)
    VALUES (${quoted(teamId)}, 'Sam Rivera', 7) RETURNING id
  `);
  psql(`
    INSERT INTO app.development_goal (player_id, title, description, created_by)
    VALUES (
      ${quoted(playerId)}, 'Receive on the back foot',
      'Open up before the ball arrives.', ${quoted(coachId)}
    )
  `);
  const gameId = psql(`
    INSERT INTO app.game (team_id, opponent, played_at, created_by)
    VALUES (${quoted(teamId)}, 'Rovers', now(), ${quoted(coachId)}) RETURNING id
  `);
  const videoId = randomUUID();
  const fixture = seedFixture(videoId);
  psql(`
    INSERT INTO app.video (
      id, game_id, original_key, original_filename, content_type, size_bytes,
      uploaded_by, status, playback_key, duration_ms, width, height, fps, ready_at
    ) VALUES (
      ${quoted(videoId)}, ${quoted(gameId)},
      ${quoted(`originals/${videoId}/source.mp4`)}, 'match.mp4', 'video/mp4', 1,
      ${quoted(coachId)}, 'ready',
      ${quoted(`playback/${videoId}/coach-720p.mp4`)}, ${fixture.duration_ms},
      ${fixture.width}, ${fixture.height}, ${fixture.fps}, now()
    )
  `);
  await page.goto(`/coach/games/${gameId}/review/${playerId}`);
  const video = page.locator("video");
  await expect(video).toBeVisible();
  await page.waitForFunction(
    () => (document.querySelector("video")?.duration ?? 0) > 0,
  );
  return { video, videoId };
}

test("a coach marks and saves a valid clip in under six seconds without a mouse", async ({
  page,
  context,
  request,
}) => {
  const { video, videoId } = await readyReview(page, context, request);
  await video.evaluate((element) => {
    element.currentTime = 1;
  });

  const started = Date.now();
  await page.keyboard.press("i");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("o");
  await expect(page.getByRole("status")).toHaveText("Saved");
  await expect(page.getByRole("list", { name: "Marked clips" })).toContainText(
    "0:01–0:04",
  );
  expect(Date.now() - started).toBeLessThan(6000);
  expect(
    Number(
      psql(
        `SELECT count(*) FROM app.observation WHERE video_id = ${quoted(videoId)}`,
      ),
    ),
  ).toBe(1);
});

test("I and O type normally in a text field and create no observation", async ({
  page,
  context,
  request,
}) => {
  const { videoId } = await readyReview(page, context, request);
  await page.evaluate(() => {
    const field = document.createElement("textarea");
    field.setAttribute("aria-label", "Test text field");
    document.body.append(field);
  });
  const field = page.getByLabel("Test text field");
  await field.focus();
  await page.keyboard.press("i");
  await page.keyboard.press("o");
  await expect(field).toHaveValue("io");
  expect(
    Number(
      psql(
        `SELECT count(*) FROM app.observation WHERE video_id = ${quoted(videoId)}`,
      ),
    ),
  ).toBe(0);
});
