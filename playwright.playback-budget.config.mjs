import { loadEnvFile } from "node:process";
import { defineConfig } from "@playwright/test";
import smoke from "./playwright.config.mjs";

loadEnvFile("apps/web/.env.local");
if (
  process.env.SUPABASE_URL !== "http://127.0.0.1:54321" ||
  process.env.APP_ORIGIN !== "http://127.0.0.1:3000"
) {
  throw new Error(
    "Playback budget measurement requires the isolated loopback stack",
  );
}
if (process.env.R2_ENDPOINT_URL !== "http://127.0.0.1:9000") {
  throw new Error(
    "Playback budget measurement requires the local MinIO endpoint",
  );
}

export default defineConfig({
  ...smoke,
  testMatch: "playback-budget.spec.mjs",
  // A 90-minute fixture encode plus twenty timed seeks.
  timeout: 45 * 60 * 1000,
  // CDP network emulation and `performance.memory` are Chromium-only, and
  // this is a performance measurement, not cross-engine correctness.
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
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
      // scripts/check-playback-budget.ps1 provisions these per run.
      DATABASE_URL: process.env.DATABASE_URL ?? "",
      OPERATOR_DATABASE_URL: process.env.OPERATOR_DATABASE_URL ?? "",
      OPERATOR_BOOTSTRAP_TOKEN: process.env.OPERATOR_BOOTSTRAP_TOKEN ?? "",
      R2_ENDPOINT_URL: process.env.R2_ENDPOINT_URL ?? "",
      R2_BUCKET: process.env.R2_BUCKET ?? "",
      R2_REGION: process.env.R2_REGION ?? "auto",
      R2_ACCESS_KEY_ID: process.env.R2_ACCESS_KEY_ID ?? "",
      R2_SECRET_ACCESS_KEY: process.env.R2_SECRET_ACCESS_KEY ?? "",
    },
    stdout: "ignore",
    stderr: "ignore",
  })),
});
