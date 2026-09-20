import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "@playwright/test";

/**
 * Task 9 acceptance: a real browser uploads a real multi-part file, the network
 * is interrupted mid-upload, the page is reloaded, the same file is reselected,
 * only the missing parts are sent, and the upload completes.
 *
 * Nothing here is stubbed. The bytes go from Chromium to MinIO through the
 * presigned URLs the API mints, so a passing run also proves that no video byte
 * travelled through the BFF or FastAPI.
 */

const origin = "http://127.0.0.1:3000";
/** Next renders its own route announcer with role=alert, so scope to the panel. */
const uploader = (page) =>
  page.getByRole("region", { name: "Upload the match video" });
const api = "http://127.0.0.1:8000";
const mail = "http://127.0.0.1:54324";
const PART_SIZE = 32 * 1024 * 1024;
// Three parts: enough for an interruption to leave real work behind.
const FILE_BYTES = PART_SIZE * 2 + 4096;

let createdEmail;
let scratch;

function resetLocalWorkspace() {
  execFileSync(
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
      "-c",
      "TRUNCATE app.player_reflection_request, app.player_reflection, app.observation, app.processing_job, app.video_upload_part, app.video, app.game, app.development_goal, app.player, app.team_membership, app.team",
    ],
    { stdio: ["ignore", "ignore", "pipe"] },
  );
}

/** Objects this run wrote must not outlive it. */
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

test.beforeEach(() => {
  resetLocalWorkspace();
  scratch = mkdtempSync(join(tmpdir(), "shoulder-upload-"));
});

test.afterEach(async ({ request }) => {
  resetLocalWorkspace();
  emptyLocalBucket();
  if (scratch) rmSync(scratch, { recursive: true, force: true });
  scratch = undefined;
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
    (user) => user.email === createdEmail,
  )) {
    if (
      !(
        await fetch(`${status.API_URL}/auth/v1/admin/users/${user.id}`, {
          method: "DELETE",
          headers,
        })
      ).ok
    ) {
      throw new Error("Local fixture deletion failed");
    }
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
  const email = `project02-${randomUUID()}@example.test`;
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
  return email;
}

async function bootstrapTeam(context, request) {
  const identity = await context.request.get("/api/auth/identity");
  expect(identity.status()).toBe(200);
  const { user_id } = await identity.json();
  const created = await request.post(`${api}/v1/teams`, {
    headers: {
      "X-Operator-Token": process.env.OPERATOR_BOOTSTRAP_TOKEN ?? "",
    },
    data: {
      name: `Project 02 ${randomUUID().slice(0, 8)}`,
      age_group: "U14",
      coach_user_id: user_id,
      season_label: "Season 2026",
      season_end_at: new Date(Date.now() + 86_400_000).toISOString(),
    },
  });
  expect(created.status()).toBe(201);
}

/** A disposable multi-part payload outside the repository. */
function payload(name = "match.mp4") {
  const path = join(scratch, name);
  writeFileSync(path, Buffer.alloc(FILE_BYTES, 7));
  return path;
}

async function addMatch(page, opponent) {
  await page.goto("/coach/upload");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Upload match",
  );
  await page.getByLabel("Date (required)").fill("2026-05-01");
  await page.getByLabel("Opponent").fill(opponent);
  await page.getByRole("button", { name: "Add match" }).click();
  await expect(page).toHaveURL(/\/coach\/upload\?game=/);
  await expect(
    page.getByRole("heading", { name: "Upload the match video" }),
  ).toBeVisible();
  return new URL(page.url()).searchParams.get("game");
}

test("an interrupted upload resumes without repeating a completed part", async ({
  page,
  context,
  request,
}) => {
  await signIn(page, context, request);
  await bootstrapTeam(context, request);
  await page.setViewportSize({ width: 1280, height: 800 });
  const gameId = await addMatch(page, "Riverside");
  const file = payload();

  // Let part one reach storage and drop the rest: a network interruption
  // partway through the file. Naming the part rather than counting keeps the
  // interruption identical in all three engines, which upload concurrently.
  await page.route("http://127.0.0.1:9000/**", async (route) => {
    if (route.request().method() !== "PUT") return route.continue();
    const part = new URL(route.request().url()).searchParams.get("partNumber");
    return part === "1" ? route.continue() : route.abort("connectionfailed");
  });

  await page.getByLabel("Match file").setInputFiles(file);
  await expect(uploader(page).getByRole("alert")).toContainText(
    /resume|missing/i,
    {
      timeout: 120000,
    },
  );

  // The honest copy: nothing claims the upload survives the tab closing.
  await expect(page.getByText("It is safe to close this tab")).toHaveCount(0);

  // The server is authoritative about what arrived. Poll for it: the component
  // reports the failure as soon as one part is refused, while part one may
  // still be in flight, and asserting immediately would race that PUT.
  const videoId = latestVideoId(gameId);
  let before;
  await expect
    .poll(async () => {
      const state = await context.request.get(
        `/api/videos/${videoId}/upload-state`,
      );
      expect(state.status()).toBe(200);
      before = await state.json();
      return before.parts.map((part) => part.part_number);
    })
    .toEqual([1]);
  expect(before.missing_part_numbers).toEqual([2, 3]);
  const firstEtag = before.parts[0].etag;

  // Reload: the browser forgot everything except its resume hint.
  await page.unroute("http://127.0.0.1:9000/**");
  await page.reload();
  await expect(
    page.getByText("An unfinished upload is waiting for this match."),
  ).toBeVisible();
  await expect(page.getByText("match.mp4")).toBeVisible();

  // Reselect the identical file; only the missing parts go out.
  const puts = [];
  page.on("request", (sent) => {
    if (
      sent.method() === "PUT" &&
      sent.url().startsWith("http://127.0.0.1:9000/")
    )
      puts.push(new URL(sent.url()).searchParams.get("partNumber"));
  });
  await page.getByLabel("Match file").setInputFiles(file);
  await expect(
    page.getByText(
      "Upload complete. It is safe to close this tab while Shoulder prepares the video.",
    ),
  ).toBeVisible({ timeout: 120000 });

  expect(puts.sort()).toEqual(["2", "3"]);

  const after = await context.request.get(
    `/api/videos/${videoId}/upload-state`,
  );
  const final = await after.json();
  expect(final.status).toBe("uploaded");
  expect(final.missing_part_numbers).toEqual([]);
  // Part one was never sent twice: its ETag is the one from the first attempt.
  expect(final.parts.find((part) => part.part_number === 1).etag).toBe(
    firstEtag,
  );

  // The processing state a coach sees after coming back.
  await page.goto(`/coach/upload?game=${gameId}`);
  await expect(page.getByText("Uploaded · preparing video")).toBeVisible();
});

test("a different file with the same name does not resume the old upload", async ({
  page,
  context,
  request,
}) => {
  await signIn(page, context, request);
  await bootstrapTeam(context, request);
  const gameId = await addMatch(page, "Eastside");

  const first = payload();
  await page.route("http://127.0.0.1:9000/**", (route) =>
    route.request().method() === "PUT"
      ? route.abort("connectionfailed")
      : route.continue(),
  );
  await page.getByLabel("Match file").setInputFiles(first);
  await expect(uploader(page).getByRole("alert")).toBeVisible({
    timeout: 120000,
  });
  await page.unroute("http://127.0.0.1:9000/**");
  await page.reload();
  const abandoned = latestVideoId(gameId);
  await expect(
    page.getByText("An unfinished upload is waiting for this match."),
  ).toBeVisible();

  // Same name, different bytes and modified time.
  const second = join(scratch, "second", "match.mp4");
  execFileSync("node", [
    "-e",
    `require("fs").mkdirSync(${JSON.stringify(join(scratch, "second"))},{recursive:true});require("fs").writeFileSync(${JSON.stringify(second)}, Buffer.alloc(${PART_SIZE + 2048}, 9))`,
  ]);
  await page.getByLabel("Match file").setInputFiles(second);
  await expect(
    page.getByText(
      "Upload complete. It is safe to close this tab while Shoulder prepares the video.",
    ),
  ).toBeVisible({ timeout: 120000 });

  // The first attempt was abandoned rather than reused for other bytes.
  const stale = await context.request.get(
    `/api/videos/${abandoned}/upload-state`,
  );
  expect((await stale.json()).status).toBe("failed");
  const fresh = latestVideoId(gameId);
  expect(fresh).not.toBe(abandoned);
});

test("an unsupported file is refused before anything is signed", async ({
  page,
  context,
  request,
}) => {
  await signIn(page, context, request);
  await bootstrapTeam(context, request);
  const gameId = await addMatch(page, "Northgate");
  const path = join(scratch, "notes.txt");
  writeFileSync(path, "not a match video");

  const calls = [];
  page.on("request", (sent) => {
    if (sent.url().includes("/videos/") || sent.url().includes("/uploads"))
      calls.push(sent.url());
  });
  await page.getByLabel("Match file").setInputFiles(path);
  await expect(uploader(page).getByRole("alert")).toContainText(
    "Choose an MP4, M4V, or MOV match file.",
  );
  expect(calls).toEqual([]);
  const listed = await context.request.get(
    `${origin}/coach/upload?game=${gameId}`,
  );
  expect(listed.status()).toBe(200);
});

/**
 * The newest video row for this match, read straight from the disposable local
 * database. The authorization assertions live in the Python suites; here the id
 * is only a handle, and reading it this way keeps no session token in the test
 * process. The fixed container name is the guard against a hosted project.
 */
function latestVideoId(gameId) {
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
      "-Atc",
      `SELECT id FROM app.video WHERE game_id = '${gameId}' ORDER BY created_at DESC LIMIT 1`,
    ],
    { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
  ).trim();
}
