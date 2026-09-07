import { execFileSync } from "node:child_process";
import { createPrivateKey, randomUUID, sign } from "node:crypto";
import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

const origin = "http://127.0.0.1:3000";
const mail = "http://127.0.0.1:54324";
const cookieName = "shoulder-auth";
let createdEmail;

test.afterEach(async () => {
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
  const messages = await (await fetch(`${mail}/api/v1/messages`)).json();
  const ids = messages.messages
    .filter((message) => message.To.some((to) => to.Address === createdEmail))
    .map((message) => message.ID);
  if (
    ids.length &&
    !(
      await fetch(`${mail}/api/v1/messages`, {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ IDs: ids }),
      })
    ).ok
  ) {
    throw new Error("Local mail cleanup failed");
  }
  createdEmail = undefined;
});

function sessionFromCookies(cookies) {
  const value = cookies
    .filter((c) => c.name === cookieName || /^shoulder-auth\.\d+$/.test(c.name))
    .sort((a, b) => a.name.localeCompare(b.name))
    .map((c) => c.value)
    .join("");
  return JSON.parse(
    Buffer.from(value.slice("base64-".length), "base64url").toString(),
  );
}

async function setSession(context, session) {
  const encoded = `base64-${Buffer.from(JSON.stringify(session)).toString("base64url")}`;
  await context.clearCookies();
  const chunks = encoded.match(/.{1,3000}/g);
  await context.addCookies(
    chunks.map((value, index) => ({
      name: chunks.length === 1 ? cookieName : `${cookieName}.${index}`,
      value,
      domain: "127.0.0.1",
      path: "/",
      httpOnly: true,
      sameSite: "Lax",
      secure: false,
    })),
  );
}

// Local-only fixture: expire the real session's access JWT with the local Auth key.
// The real Auth refresh token and refresh endpoint are unchanged; no mocked service.
function expireAccessToken(token) {
  const [header, payload] = token.split(".");
  const claims = JSON.parse(Buffer.from(payload, "base64url").toString());
  claims.exp = Math.floor(Date.now() / 1000) - 60;
  claims.iat = claims.exp - 3600;
  const body = `${header}.${Buffer.from(JSON.stringify(claims)).toString("base64url")}`;
  const keys = JSON.parse(
    readFileSync("supabase/.env.signing-keys.json", "utf8").replace(
      /^\uFEFF/,
      "",
    ),
  );
  const key = createPrivateKey({ key: keys[0], format: "jwk" });
  return `${body}.${sign("sha256", Buffer.from(body), { key, dsaEncoding: "ieee-p1363" }).toString("base64url")}`;
}

test("real PKCE, identity forwarding, refresh, replay, and sign-out", async ({
  page,
  context,
  request,
}) => {
  const email = `task3-${randomUUID()}@example.test`;
  createdEmail = email;
  await page.goto("/auth/sign-in");
  await page.getByLabel("Email address").fill(email);
  await page.getByRole("button", { name: "Email a sign-in link" }).click();
  await expect(page.getByRole("status")).toContainText("check your email");
  const pkceCookies = await context.cookies();
  expect(
    pkceCookies.some((c) => c.name.includes("code-verifier") && c.httpOnly),
  ).toBe(true);

  // A rate-limited resend must remain generic and not invalidate the first
  // link's PKCE flow, including the SDK's default fixed verifier cookie.
  const resend = await context.request.post("/auth/magic-link", {
    headers: { Origin: origin },
    form: { email },
    maxRedirects: 0,
  });
  expect(resend.status()).toBe(303);
  expect(resend.headers().location).toBe(`${origin}/auth/sign-in?sent=1`);

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
  // Capture without a browser trace or logging any token-bearing URL.
  const verification = await request.get(link, { maxRedirects: 0 });
  expect(verification.status()).toBe(303);
  const callback = verification.headers().location;
  expect(new URL(callback).pathname).toBe("/auth/callback");
  // The context request shares this browser's cookie jar and uses real HTTP.
  // Inspect wire attributes because Windows WebKit misreports SameSite and
  // omits redirect Set-Cookie headers from its page response API.
  const exchanged = await context.request.get(
    `${callback}&next=https://evil.invalid`,
    { maxRedirects: 0 },
  );
  expect(exchanged.status()).toBe(303);
  expect(exchanged.headers().location).toBe(`${origin}/auth/session`);
  const cookieAttributes = exchanged
    .headersArray()
    .filter((h) => h.name.toLowerCase() === "set-cookie")
    .map((h) =>
      h.value
        .split(";")
        .slice(1)
        .map((attribute) => attribute.trim().toLowerCase()),
    );
  await page.goto(exchanged.headers().location);
  await expect(page.getByRole("heading")).toHaveText("You’re signed in.");
  expect(new URL(page.url()).pathname).toBe("/auth/session");
  expect(await page.evaluate(() => document.cookie)).not.toContain(cookieName);
  const cookies = await context.cookies();
  expect(cookieAttributes.length).toBeGreaterThan(0);
  for (const attributes of cookieAttributes) {
    expect(attributes).toContain("httponly");
    expect(attributes).toContain("samesite=lax");
    expect(attributes).toContain("path=/");
  }
  for (const cookie of cookies.filter((c) => c.name.startsWith(cookieName))) {
    expect({
      name: cookie.name,
      httpOnly: cookie.httpOnly,
      path: cookie.path,
    }).toEqual({
      name: cookie.name,
      httpOnly: true,
      path: "/",
    });
  }
  const session = sessionFromCookies(cookies);
  const identity = await context.request.get("/api/auth/identity", {
    headers: { "X-User-Id": randomUUID(), "X-Role": "coach" },
  });
  expect(identity.status()).toBe(200);
  expect(identity.headers()["cache-control"]).toContain("no-store");
  const identityBody = await identity.json();
  expect(Object.keys(identityBody)).toEqual(["user_id"]);
  const api = await request.get("http://127.0.0.1:8000/v1/auth/identity", {
    headers: { Authorization: `Bearer ${session.access_token}` },
  });
  expect(api.status()).toBe(200);
  expect(await api.json()).toEqual(identityBody);
  expect((await request.get("http://127.0.0.1:8000/v1/me")).status()).toBe(404);

  const expired = expireAccessToken(session.access_token);
  expect(
    (
      await request.get("http://127.0.0.1:8000/v1/auth/identity", {
        headers: { Authorization: `Bearer ${expired}` },
      })
    ).status(),
  ).toBe(401);
  await setSession(context, {
    ...session,
    access_token: expired,
    expires_at: 1,
  });
  const refreshed = await context.request.get("/api/auth/identity");
  expect(refreshed.status()).toBe(200);
  expect(await refreshed.json()).toEqual(identityBody);
  const refreshedSession = sessionFromCookies(await context.cookies());
  expect(refreshedSession.access_token !== expired).toBe(true);
  expect(refreshed.headers()["set-cookie"]).toContain("HttpOnly");

  await page.goto("/auth/session");
  const signOutResponse = page.waitForResponse((response) =>
    response.url().endsWith("/auth/sign-out"),
  );
  await page.getByRole("button", { name: "Sign out" }).click();
  expect((await signOutResponse).status()).toBe(303);
  await expect(page.getByRole("heading")).toHaveText("Sign in to Shoulder");
  expect(
    (await context.cookies()).some((c) => c.name.startsWith(cookieName)),
  ).toBe(false);
  expect((await context.request.get("/api/auth/identity")).status()).toBe(401);
  await setSession(context, refreshedSession);
  expect((await context.request.get("/api/auth/identity")).status()).toBe(401);
  expect(
    (
      await request.get("http://127.0.0.1:8000/v1/auth/identity", {
        headers: { Authorization: `Bearer ${refreshedSession.access_token}` },
      })
    ).status(),
  ).toBe(401);
  // A revoked refresh grant cannot restore expired session identity.
  await setSession(context, {
    ...refreshedSession,
    access_token: expired,
    expires_at: 1,
  });
  expect((await context.request.get("/api/auth/identity")).status()).toBe(401);
  await context.clearCookies();
  await context.addCookies(pkceCookies);
  await page.goto(callback);
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "could not sign you in",
  );
  expect((await context.request.get("/api/auth/identity")).status()).toBe(401);
});

test("CSRF, invalid callbacks, signed-out and malformed sessions fail closed", async ({
  page,
  context,
  request,
}) => {
  for (const route of ["/auth/magic-link", "/auth/sign-out"]) {
    for (const headers of [
      {},
      { Origin: "https://evil.invalid" },
      { Origin: "null" },
    ]) {
      expect(
        (
          await request.post(route, {
            headers,
            form: { email: "test@example.test" },
          })
        ).status(),
      ).toBe(403);
    }
  }
  expect(
    (
      await request.post("/auth/magic-link", {
        headers: { Origin: origin },
        form: { email: "invalid" },
      })
    ).status(),
  ).toBe(400);
  for (const query of [
    "",
    "?code=invalid",
    "?code=a&code=b",
    "?code=a&sb_flow_id=invalid!",
    "?code=a&sb_flow_id=abcdefgh&sb_flow_id=ijklmnop",
    "?error=bad&next=//evil.invalid",
  ]) {
    const response = await request.get(`/auth/callback${query}`, {
      maxRedirects: 0,
    });
    expect(response.headers().location).toBe(`${origin}/auth/sign-in?error=1`);
  }
  await context.addCookies([
    { name: cookieName, value: "malformed", domain: "127.0.0.1", path: "/" },
  ]);
  expect((await context.request.get("/api/auth/identity")).status()).toBe(401);
  await page.goto("/auth/session");
  await expect(page.getByRole("heading")).toHaveText("Sign in to Shoulder");
  expect(
    (await request.get("http://127.0.0.1:8000/v1/auth/identity")).status(),
  ).toBe(401);
});
