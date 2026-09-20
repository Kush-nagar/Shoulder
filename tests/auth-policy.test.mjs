import assert from "node:assert/strict";
import { test } from "node:test";
import {
  authConfig,
  verifiedRedirectPath,
  validClaims,
  validOrigin,
} from "../apps/web/lib/auth/policy.ts";

const env = {
  APP_ORIGIN: "http://127.0.0.1:3000",
  AUTH_ALLOW_LOCAL_HTTP: "true",
  SUPABASE_URL: "http://127.0.0.1:54321",
  SUPABASE_PUBLISHABLE_KEY: "test-placeholder",
  API_BASE_URL: "http://127.0.0.1:8000",
};

test("HTTP cookies require explicit loopback opt-in; HTTPS cookies always secure", () => {
  assert.equal(authConfig(env).secure, false);
  assert.throws(() => authConfig({ ...env, AUTH_ALLOW_LOCAL_HTTP: "false" }));
  assert.throws(() =>
    authConfig({ ...env, APP_ORIGIN: "http://remote.invalid" }),
  );
  assert.equal(
    authConfig({ ...env, APP_ORIGIN: "https://app.example.test" }).secure,
    true,
  );
  assert.throws(() =>
    authConfig({ ...env, APP_ORIGIN: "https://app.example.test/path" }),
  );
});

test("mutations require exact configured origin and host; forwarded identity is irrelevant", () => {
  const headers = new Headers({
    origin: env.APP_ORIGIN,
    host: "127.0.0.1:3000",
  });
  assert.equal(validOrigin(headers, env.APP_ORIGIN), true);
  for (const origin of [
    "null",
    "https://evil.invalid",
    "http://127.0.0.1:3000.evil.invalid",
  ]) {
    headers.set("origin", origin);
    assert.equal(validOrigin(headers, env.APP_ORIGIN), false);
  }
  headers.delete("origin");
  assert.equal(validOrigin(headers, env.APP_ORIGIN), false);
  headers.set("origin", env.APP_ORIGIN);
  headers.set("host", "evil.invalid");
  headers.set("x-forwarded-host", "127.0.0.1:3000");
  assert.equal(validOrigin(headers, env.APP_ORIGIN), false);
});

test("verified claims still require the intended issuer, audience, expiry, and UUID", () => {
  const claims = {
    session_id: "00000000-0000-4000-8000-000000000002",
    sub: "00000000-0000-4000-8000-000000000001",
    iss: `${env.SUPABASE_URL}/auth/v1`,
    aud: "authenticated",
    exp: Math.floor(Date.now() / 1000) + 300,
  };
  assert.equal(validClaims(claims, env.SUPABASE_URL), true);
  for (const patch of [
    { sub: "coach" },
    { iss: "https://evil.invalid" },
    { aud: "other" },
    { exp: 1 },
  ]) {
    assert.equal(validClaims({ ...claims, ...patch }, env.SUPABASE_URL), false);
  }
});

test("email redirects allow only exact authenticated product routes", () => {
  const goal = "00000000-0000-4000-8000-000000000001";
  const publication = "00000000-0000-4000-8000-000000000002";
  const game = "00000000-0000-4000-8000-000000000003";
  const player = "00000000-0000-4000-8000-000000000004";
  for (const path of [
    `/player/goals/${goal}`,
    `/player/goals/${goal}?publication=${publication}`,
    `/coach/games/${game}`,
    `/coach/players/${player}`,
  ]) {
    assert.equal(verifiedRedirectPath(path), path);
  }
  for (const unsafe of [
    "https://evil.invalid/player/goals/00000000-0000-4000-8000-000000000001",
    "//evil.invalid/player/goals/00000000-0000-4000-8000-000000000001",
    "/\\evil.invalid",
    `/player/goals/${goal}?publication=${publication}&next=https://evil.invalid`,
    `/player/goals/${goal}?publication=not-a-uuid`,
    `/coach/games/${game}?next=https://evil.invalid`,
    `/coach/players/${player}#https://evil.invalid`,
    "/auth/session",
    "/player",
  ]) {
    assert.equal(verifiedRedirectPath(unsafe), null, unsafe);
  }
});
