import { loadEnvFile } from "node:process";
import { defineConfig } from "@playwright/test";
import smoke from "./playwright.config.mjs";

loadEnvFile("apps/web/.env.local");
if (
  process.env.SUPABASE_URL !== "http://127.0.0.1:54321" ||
  process.env.APP_ORIGIN !== "http://127.0.0.1:3000"
) {
  throw new Error("Auth integration tests require the isolated loopback stack");
}

export default defineConfig({
  ...smoke,
  testMatch: "auth.spec.mjs",
  timeout: 60000,
  use: {
    baseURL: process.env.APP_ORIGIN,
    trace: "off",
    screenshot: "off",
    video: "off",
  },
  webServer: smoke.webServer.map((server) => ({
    ...server,
    env: {
      ...server.env,
      SUPABASE_AUTH_ISSUER: `${process.env.SUPABASE_URL}/auth/v1`,
      // scripts/check-auth.ps1 provisions this per run; never stored.
      DATABASE_URL: process.env.DATABASE_URL ?? "",
    },
    stdout: "ignore",
    stderr: "ignore",
  })),
});
