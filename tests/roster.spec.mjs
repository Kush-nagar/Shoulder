import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const origin = "http://127.0.0.1:3000";
const api = "http://127.0.0.1:8000";
const mail = "http://127.0.0.1:54324";
// docs/09-frontend-design-system.md, coach lists and forms.
const widths = [
  [768, 1024],
  [1024, 768],
  [1280, 800],
  [1440, 900],
];
let createdEmail;

test.afterEach(async ({ request }) => {
  if (!createdEmail) return;
  // Test process only. The privileged local cleanup credential never reaches
  // a web/API process, browser, file, trace, or assertion output.
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
  if (ids.length) {
    await request.delete(`${mail}/api/v1/messages`, { data: { IDs: ids } });
  }
  createdEmail = undefined;
});

/** Real magic-link sign-in against the isolated loopback stack. */
async function signIn(page, context, request) {
  const email = `project01-${randomUUID()}@example.test`;
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

/** A coach role exists only because a team membership row exists. */
async function bootstrapTeam(context, request) {
  const identity = await context.request.get("/api/auth/identity");
  expect(identity.status()).toBe(200);
  const { user_id } = await identity.json();
  const created = await request.post(`${api}/v1/teams`, {
    headers: {
      "X-Operator-Token": process.env.OPERATOR_BOOTSTRAP_TOKEN ?? "",
    },
    data: {
      name: `Project 01 ${randomUUID().slice(0, 8)}`,
      age_group: "U14",
      coach_user_id: user_id,
      season_label: "Season 2026",
      season_end_at: new Date(Date.now() + 86_400_000).toISOString(),
    },
  });
  expect(created.status()).toBe(201);
}

async function names(page, selector) {
  return page
    .locator(selector)
    .evaluateAll((elements) =>
      elements.map((element) =>
        (
          element.getAttribute("aria-label") ??
          element.textContent ??
          ""
        ).trim(),
      ),
    );
}

test("keyboard path through paste, preview, confirm, and saved", async ({
  page,
  context,
  request,
}) => {
  await signIn(page, context, request);
  await bootstrapTeam(context, request);
  await page.setViewportSize({ width: 1280, height: 800 });

  // The role-aware redirect resolves from the database, not the route.
  await page.goto("/");
  await expect(page).toHaveURL(`${origin}/coach/roster`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Players");

  const paste = page.getByLabel("Paste your roster");
  // Reachable by keyboard alone from the top of the document.
  await page.keyboard.press("Tab");
  for (
    let step = 0;
    step < 20 && !(await paste.evaluate((el) => el === document.activeElement));
    step += 1
  ) {
    await page.keyboard.press("Tab");
  }
  await expect(paste).toBeFocused();

  const footnote = page.getByText("All rows are added together");
  const before = await footnote.boundingBox();
  await expect(page.getByText("Nothing pasted yet.")).toBeVisible();

  await page.keyboard.type(
    "Ada Nkemdirim, 7, Winger\nBo Sun, 9, Striker\n\nCam Ruiz, 11",
  );
  await expect(page.getByText("3 rows ready to add.")).toBeVisible();
  // The preview region reserves its geometry, so nothing below it moves.
  expect(await footnote.boundingBox()).toEqual(before);

  const confirm = page.getByRole("button", { name: "Add 3 players" });
  await page.keyboard.press("Tab");
  await expect(confirm).toBeFocused();
  await page.keyboard.press("Enter");

  await expect(page.getByRole("status")).toContainText("3 players were added.");
  for (const name of ["Ada Nkemdirim", "Bo Sun", "Cam Ruiz"]) {
    await expect(page.getByRole("link", { name, exact: true })).toBeVisible();
  }
  // Preview rows are honest about a bad row and block the all-or-nothing save.
  await page.getByText("Add several at once").click();
  const second = page.getByLabel("Paste your roster");
  await second.fill("Dee Okafor, 7\nEli Park, 7");
  await expect(
    page.getByText("2 of 2 rows need a fix.", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Add 2 players" }),
  ).toBeDisabled();
});

test("inline add row adds one player without collecting an email", async ({
  page,
  context,
  request,
}) => {
  await signIn(page, context, request);
  await bootstrapTeam(context, request);
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/coach/roster");

  await page.getByLabel("Name (required)").click();
  await page.keyboard.type("Fay Adeyemi");
  await page.keyboard.press("Tab");
  await page.keyboard.type("4");
  await page.keyboard.press("Tab");
  await page.keyboard.type("Defender");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Add player" })).toBeFocused();
  await page.keyboard.press("Enter");

  await expect(page.getByRole("status")).toContainText(
    "Fay Adeyemi was added.",
  );
  await expect(
    page.getByRole("link", { name: "Fay Adeyemi", exact: true }),
  ).toBeVisible();
  // Account state is neutral and no address is rendered anywhere on the roster.
  await expect(page.getByRole("cell", { name: "Not linked" })).toBeVisible();
  expect(await page.locator("body").innerText()).not.toContain("@");

  // A player without a goal offers the goal as its next action.
  await page.getByRole("link", { name: "Set a goal for Fay Adeyemi" }).click();
  await expect(page).toHaveURL(/\/coach\/players\/[0-9a-f-]{36}$/);
  await page.getByLabel("Goal (required)").fill("Scan before receiving");
  await page.getByRole("button", { name: "Set a goal" }).click();
  await expect(page.getByRole("status")).toContainText("Goal set.");
  await expect(page.getByText("Scan before receiving")).toBeVisible();
});

test("accessible names, axe, and no horizontal scroll at coach widths", async ({
  page,
  context,
  request,
}, testInfo) => {
  await signIn(page, context, request);
  await bootstrapTeam(context, request);
  await page.goto("/coach/roster");
  await page.getByLabel("Paste your roster").fill("Gia Moreau, 2, Fullback");
  await page.getByRole("button", { name: "Add 1 player" }).click();
  await expect(page.getByRole("status")).toContainText("1 player was added.");
  const detail = await page
    .getByRole("link", { name: "Gia Moreau", exact: true })
    .getAttribute("href");

  for (const [width, height] of widths) {
    await page.setViewportSize({ width, height });
    for (const route of ["/coach/roster", detail]) {
      await page.goto(route);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      // Every interactive control carries an accessible name.
      for (const name of await names(page, "button, a[href], summary")) {
        expect(name).not.toBe("");
      }
      expect(
        await page
          .locator("input, textarea")
          .evaluateAll(
            (elements) =>
              elements.filter(
                (element) =>
                  !element.labels?.length &&
                  !element.getAttribute("aria-label"),
              ).length,
          ),
      ).toBe(0);
      expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
      await page.screenshot({
        path: testInfo.outputPath(
          `${route.includes("roster") ? "roster" : "player"}-${width}.png`,
        ),
        fullPage: true,
      });
    }
  }

  // No score, rank, or engagement language reaches a coach screen either.
  const text = (await page.locator("body").innerText()).toLowerCase();
  for (const word of [
    "score",
    "rank",
    "average",
    "percentile",
    "streak",
    "badge",
    "insight",
    "level up",
    "ai-powered",
  ]) {
    expect(text).not.toContain(word);
  }
});
